"""L0: Unicode and script normalization.

This is the cheapest defence and the one most often skipped. Attackers bypass
keyword and classifier filters far more often by *encoding* an instruction
(homoglyphs, zero-width joiners, full-width forms, bidi overrides) than by
inventing new semantics.

For a bilingual deployment this layer matters twice over: Arabic text can be
smuggled past an English detector via presentation forms and Arabic-Indic
digits, and Latin text can be disguised with Cyrillic/Greek homoglyphs.

Everything here is pure ``unicodedata`` + ``regex`` so it runs on every request
with no model and no measurable cost.
"""

from __future__ import annotations

import unicodedata

#: Zero-width and other invisible formatting characters used to split tokens.
_INVISIBLE = {
    '\u200b',  # zero width space
    '\u200c',  # zero width non-joiner
    '\u200d',  # zero width joiner
    '\u200e',  # left-to-right mark
    '\u200f',  # right-to-left mark
    '\u2060',  # word joiner
    '\u2061',  # function application
    '\u2062',  # invisible times
    '\u2063',  # invisible separator
    '\u2064',  # invisible plus
    '\ufeff',  # zero width no-break space
    '\u00ad',  # soft hyphen
    '\u180e',  # mongolian vowel separator
}

#: Bidirectional overrides/embeddings. They can visually reorder text so a
#: reviewer reads something different from what the model receives. No
#: legitimate CBO prompt needs them, so they are removed outright.
_BIDI_CONTROLS = {
    '\u202a',  # LRE
    '\u202b',  # RLE
    '\u202c',  # PDF
    '\u202d',  # LRO
    '\u202e',  # RLO
    '\u2066',  # LRI
    '\u2067',  # RLI
    '\u2068',  # FSI
    '\u2069',  # PDI
}

#: Arabic presentation forms (U+FB50-U+FEFF) are compatibility characters that
#: NFKC folds back to base letters. Listing the ranges lets us assert coverage.
_PRESENTATION_FORM_RANGES = ((0xFB50, 0xFDFF), (0xFE70, 0xFEFF))

#: Scripts whose letters are visually confusable with Latin. A single-token
#: prompt mixing these with Latin is a strong homoglyph signal.
_CONFUSABLE_RANGES = (
    (0x0400, 0x04FF),  # Cyrillic
    (0x0370, 0x03FF),  # Greek
    (0x0530, 0x058F),  # Armenian
)

_ARABIC_RANGES = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
)

_ARABIC_INDIC_ZERO = 0x0660  # ٠
_EXTENDED_ARABIC_INDIC_ZERO = 0x06F0  # ۰


def _in_ranges(codepoint: int, ranges) -> bool:
    return any(low <= codepoint <= high for low, high in ranges)


def is_arabic_char(char: str) -> bool:
    return _in_ranges(ord(char), _ARABIC_RANGES)


def has_arabic(text: str) -> bool:
    return any(is_arabic_char(char) for char in text)


def strip_invisible(text: str) -> str:
    """Remove zero-width, bidi and other invisible control characters."""
    return ''.join(
        char for char in text if char not in _INVISIBLE and char not in _BIDI_CONTROLS
    )


def fold_digits(text: str) -> str:
    """Fold Arabic-Indic and Extended Arabic-Indic digits to ASCII.

    ``"٠١٢"`` and ``"012"`` must compare equal, otherwise rules written with
    ASCII digits silently miss Arabic input and vice versa.
    """
    out = []
    for char in text:
        codepoint = ord(char)
        if _ARABIC_INDIC_ZERO <= codepoint <= _ARABIC_INDIC_ZERO + 9:
            out.append(chr(ord('0') + codepoint - _ARABIC_INDIC_ZERO))
        elif _EXTENDED_ARABIC_INDIC_ZERO <= codepoint <= _EXTENDED_ARABIC_INDIC_ZERO + 9:
            out.append(chr(ord('0') + codepoint - _EXTENDED_ARABIC_INDIC_ZERO))
        else:
            out.append(char)
    return ''.join(out)


def strip_arabic_diacritics(text: str) -> str:
    """Remove Arabic harakat/tatweel so ``سِحر`` and ``سحر`` match the same rule.

    Only marks are removed; letters and their Arabic-specific forms are kept so
    that ``أ/ا`` and ``ة/ه`` distinctions survive for policy rules that care.
    """
    out = []
    for char in text:
        codepoint = ord(char)
        # U+064B..U+065F harakat, U+0670 superscript alef, U+0640 tatweel,
        # and the Quranic annotation marks in U+06D6..U+06ED.
        if 0x064B <= codepoint <= 0x065F or codepoint in (0x0670, 0x0640):
            continue
        if 0x06D6 <= codepoint <= 0x06ED:
            continue
        out.append(char)
    return ''.join(out)


#: Alef variants folded to bare alef. Arabic orthography is inconsistent in
#: real user input: ``أهمل`` / ``اهمل`` and ``إظهار`` / ``اظهار`` are the same
#: word. Without this fold an attacker trivially evades every rule by writing
#: the hamza form, which is exactly what happened in the first test run.
_ALEF_FOLD = {
    '\u0622': '\u0627',  # آ -> ا
    '\u0623': '\u0627',  # أ -> ا
    '\u0625': '\u0627',  # إ -> ا
    '\u0671': '\u0627',  # ٱ -> ا
    '\u0649': '\u064a',  # ى -> ي (alef maqsura -> yeh)
    '\u0629': '\u0647',  # ة -> ه (teh marbuta -> heh)
}


def fold_arabic_letters(text: str) -> str:
    """Fold Arabic orthographic variants so rules match regardless of spelling.

    Applies the standard pairings used for Arabic search and matching:
    alef with/without hamza, alef maqsura/yeh, and teh marbuta/heh.

    This is *over-matching* by design: normalising ``أ`` to ``ا`` cannot create
    a match that a native reader would consider wrong, because the two are the
    same word. It only makes the rules reachable by both spellings.
    """
    return ''.join(_ALEF_FOLD.get(char, char) for char in text)


def collapse_whitespace(text: str) -> str:
    """Collapse all whitespace runs to a single space."""
    return ' '.join(text.split())


def despace(text: str) -> str:
    """Undo letter-spacing evasion while preserving word boundaries.

    ``"i g n o r e   a l l"`` becomes ``"ignore all"``: consecutive
    single-character tokens are joined into a word, and a run of two or more
    spaces (written by the attacker between words) survives as the word break.

    Only applied when *every* token is a single character, which does not occur
    in normal Arabic or English prose, so there is no false-positive risk.
    """
    tokens = [token for token in text.split(' ') if token]
    if len(tokens) < 4 or not all(len(token) == 1 for token in tokens):
        return text
    words = []
    for chunk in text.split('  '):
        joined = ''.join(part for part in chunk.split(' ') if part)
        if joined:
            words.append(joined)
    return ' '.join(words)


def mixed_script_suspicion(text: str) -> bool:
    """True when a *single token* mixes Latin with a confusable script.

    ``"pаypal"`` (Cyrillic а) and ``"security"`` (Greek ε) are flagged;
    ``"CBO AI"`` and normal Arabic/English code-switching are not, because
    switching between words is normal and switching *inside* a word is not.
    """
    for token in text.split():
        has_latin = False
        has_confusable = False
        for char in token:
            if not char.isalpha():
                continue
            if char.isascii():
                has_latin = True
            elif _in_ranges(ord(char), _CONFUSABLE_RANGES):
                has_confusable = True
        if has_latin and has_confusable:
            return True
    return False


#: Cyrillic, Greek and Armenian letters that render like a Latin letter.
#: Deliberately limited to near-identical glyphs so that folding cannot turn
#: one real Latin word into another.
_CONFUSABLES = {
    # Cyrillic lowercase
    'а': 'a', 'в': 'b', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'у': 'y',
    'х': 'x', 'і': 'i', 'ј': 'j', 'ѕ': 's', 'ԁ': 'd', 'һ': 'h', 'ӏ': 'l',
    'ԛ': 'q', 'ԝ': 'w', 'к': 'k', 'ү': 'y', 'ɡ': 'g',
    # Cyrillic uppercase
    'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M', 'Н': 'H', 'О': 'O',
    'Р': 'P', 'С': 'C', 'Т': 'T', 'Х': 'X', 'У': 'Y', 'І': 'I', 'Ј': 'J',
    'Ѕ': 'S', 'Ԁ': 'D', 'Ԛ': 'Q', 'Ԝ': 'W',
    # Greek
    'α': 'a', 'ο': 'o', 'ν': 'v', 'ρ': 'p', 'ι': 'i', 'κ': 'k', 'υ': 'u',
    'χ': 'x', 'ε': 'e', 'τ': 't',
    'Α': 'A', 'Β': 'B', 'Ε': 'E', 'Ζ': 'Z', 'Η': 'H', 'Ι': 'I', 'Κ': 'K',
    'Μ': 'M', 'Ν': 'N', 'Ο': 'O', 'Ρ': 'P', 'Τ': 'T', 'Υ': 'Y', 'Χ': 'X',
    # Armenian
    'օ': 'o', 'ս': 'u', 'հ': 'h',
}


def _fold_token(token: str) -> str:
    return ''.join(_CONFUSABLES.get(char, char) for char in token)


def fold_confusables(text: str) -> str:
    """Fold Cyrillic/Greek/Armenian look-alikes to Latin where they disguise Latin.

    ``"іgnore"`` (Cyrillic і) becomes ``"ignore"`` so the L1 rules see the
    word the model will read. A token is folded when it already contains a
    Latin letter (a mixed-script word is never legitimate), or when the text
    is mostly Latin and the token is made only of look-alikes (a whole word
    spelled in Cyrillic inside English prose). Genuine Russian or Greek text
    is left alone because Latin is not the dominant script there.
    """
    latin = confusable = 0
    for char in text:
        if not char.isalpha():
            continue
        if char.isascii():
            latin += 1
        elif _in_ranges(ord(char), _CONFUSABLE_RANGES):
            confusable += 1
    if not confusable:
        return text
    latin_dominant = latin > confusable

    def fold(token: str) -> str:
        letters = [char for char in token if char.isalpha()]
        if not any(_in_ranges(ord(char), _CONFUSABLE_RANGES) for char in letters):
            return token
        if any(char.isascii() for char in letters):
            return _fold_token(token)
        # len >= 2 leaves lone Greek symbols ("the α coefficient") untouched.
        if latin_dominant and len(letters) >= 2 and all(char in _CONFUSABLES for char in letters):
            return _fold_token(token)
        return token

    return ' '.join(fold(token) for token in text.split(' '))


def normalize(text: str) -> str:
    """Canonical form used by every downstream layer and classifier.

    Order matters: invisible characters are stripped *before* NFKC so that
    already-decomposed sequences cannot be recombined into a different token,
    and diacritics are folded *after* NFKC so that presentation forms have
    already been resolved to their base letters.
    """
    if not text:
        return ''
    text = strip_invisible(text)
    text = unicodedata.normalize('NFKC', text)
    text = strip_invisible(text)  # NFKC can reintroduce nothing, but stay safe
    text = strip_arabic_diacritics(text)
    text = fold_arabic_letters(text)
    text = fold_digits(text)
    # Homoglyphs are folded after NFKC (which already resolves full-width and
    # mathematical Latin forms) and before de-spacing, which needs real letters.
    text = fold_confusables(text)
    # De-space before collapsing whitespace, because it needs the original
    # multi-space word boundaries to rebuild words correctly.
    text = despace(text)
    text = collapse_whitespace(text)
    return text.strip()


def coverage(text: str) -> dict[str, bool]:
    """Signals used by the evaluator to spot *evasion* rather than content.

    Returned to the caller for logging so IT can see how often inputs arrive
    with homoglyph or bidi trickery -- itself a useful threat indicator.
    """
    raw = text or ''
    return {
        'has_arabic': has_arabic(raw),
        'has_invisible': any(char in _INVISIBLE or char in _BIDI_CONTROLS for char in raw),
        'has_presentation_forms': any(
            _in_ranges(ord(char), _PRESENTATION_FORM_RANGES) for char in raw
        ),
        'mixed_script': mixed_script_suspicion(unicodedata.normalize('NFKC', raw)),
    }
