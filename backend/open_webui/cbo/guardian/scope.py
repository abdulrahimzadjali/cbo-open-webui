"""L4: CBO business-scope policy.

The most important design decision in the whole guardian: business scope is an
**allowlist owned by CBO IT**, not a vendor harm taxonomy. No off-the-shelf
guard model knows what "CBO business" means, and Microsoft documents explicitly
that a prompt attack classifier "doesn't establish that the request is
aligned with the system's intended use".

Scope checking is *not* keyword blocking. A prompt is in scope if it contains
a recognised CBO business signal (either language). Prompts with no signal at
all are only out of scope when the deployment opts into strict mode, because a
terse but legitimate prompt ("what is the deadline?") carries no signal.

Arabic matching uses light stemming: a suffix/prefix-insensitive comparison so
that ``التعميم`` / ``التعاميم`` / ``تعميم`` all match one root entry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from open_webui.cbo.guardian.normalize import has_arabic, normalize, strip_arabic_diacritics
from open_webui.cbo.guardian.types import Layer, Verdict


@dataclass(frozen=True)
class ScopeDomain:
    """One CBO business domain and the signals that indicate it."""

    id: str
    label_en: str
    label_ar: str
    #: English/Latin keyword stems, matched as whole words.
    terms_en: tuple[str, ...] = ()
    #: Arabic root forms, matched as normalized substrings.
    terms_ar: tuple[str, ...] = ()


#: Default CBO business domains.
#:
#: IT owns this list and can extend it in Admin Settings without a release.
#: Keep each term specific enough that it does not match conversational
#: filler: "credit" is fine, "the" is not.
DEFAULT_DOMAINS: tuple[ScopeDomain, ...] = (
    ScopeDomain(
        id='banking_supervision',
        label_en='Banking supervision & licensing',
        label_ar='الرقابة المصرفية والترخيص',
        terms_en=(
            'supervision', 'supervisory', 'license', 'licensing', 'licensed',
            'branch', 'branches', 'bank', 'banks', 'banking', 'aml', 'cft',
            'anti-money', 'kyc', 'compliance', 'sanction', 'sanctions',
            'circular', 'circulars', 'directive', 'directives', 'regulation',
            'capital adequacy', 'liquidity', 'basel', 'stress test',
        ),
        terms_ar=(
            'رقابة', 'مصرف', 'بنك', 'بنوك', 'ترخيص', 'فرع', 'فروع',
            'غسل', 'الاموال', 'ارهاب', 'ائتماني', 'تعميم', 'تعميمات',
            'ضوابط', 'لائحة', 'لوائح', 'كفاية', 'سيولة', 'امتثال',
        ),
    ),
    ScopeDomain(
        id='monetary_policy',
        label_en='Monetary policy & markets',
        label_ar='السياسة النقدية والأسواق',
        terms_en=(
            'monetary', 'policy rate', 'interest rate', 'inflation', 'cpi',
            'reserve', 'reserves', 'fx', 'foreign exchange', 'exchange rate',
            'repo', 'open market', 'treasury', 'bond', 'bonds', 'sukuk',
            'money supply', 'currency', 'rial', 'omr', 'gold',
        ),
        terms_ar=(
            'نقد', 'نقدية', 'تضخم', 'احتياطي', 'فائدة', 'صرف', 'عملة',
            'ريال', 'سندات', 'صكوك', 'سياسة', 'اسعار', 'ذهب',
        ),
    ),
    ScopeDomain(
        id='statistics_research',
        label_en='Statistics, research & analysis',
        label_ar='الإحصاءات والبحوث والتحليل',
        terms_en=(
            'statistics', 'statistic', 'statistical', 'data', 'dataset',
            'report', 'reports', 'quarterly', 'annual', 'gdp', 'balance of payments',
            'research', 'analysis', 'analyse', 'analyze', 'forecast', 'trend',
            'indicator', 'indicators', 'chart', 'summary', 'summarise', 'summarize',
        ),
        terms_ar=(
            'احصاء', 'احصائية', 'احصاءات', 'بيانات', 'تقرير', 'تقارير',
            'ربع', 'سنوي', 'ناتج', 'ميزان', 'بحث', 'تحليل', 'مؤشر',
            'اتجاه', 'ملخص', 'لخص',
        ),
    ),
    ScopeDomain(
        id='regulatory_reporting',
        label_en='Regulatory reporting & finance',
        label_ar='التقارير الرقابية والمالية',
        terms_en=(
            'reporting', 'submit', 'submission', 'filing', 'return', 'returns',
            'audit', 'auditor', 'financial', 'statement', 'statements',
            'ledger', 'accounting', 'invoice', 'budget', 'revenue',
            'expense', 'payment', 'transfer', 'swift', 'ibr', 'settlement',
        ),
        terms_ar=(
            'رفع', 'تقديم', 'ايداع', 'تدقيق', 'مراجع', 'مالي', 'مالية',
            'قائمة', 'قوائم', 'فاتورة', 'ميزانية', 'ايراد', 'مصروف',
            'دفع', 'تحويل', 'تسوية', 'محاسب',
        ),
    ),
    ScopeDomain(
        id='internal_operations',
        label_en='Internal operations, HR & IT',
        label_ar='العمليات الداخلية والموارد البشرية وتقنية المعلومات',
        terms_en=(
            'hr', 'human resources', 'leave', 'annual leave', 'salary',
            'payroll', 'employee', 'employees', 'staff', 'training',
            'policy', 'procedure', 'procedures', 'template', 'draft',
            'meeting', 'minutes', 'agenda', 'email', 'letter', 'memo',
            'system', 'login', 'password', 'account', 'vpn', 'laptop',
            'software', 'access', 'request', 'it support', 'helpdesk',
            'translate', 'translation', 'summarise', 'summarize',
        ),
        terms_ar=(
            'موارد', 'بشرية', 'موظف', 'موظفين', 'راتب', 'رواتب', 'اجازة',
            'تدريب', 'سياسة', 'اجراء', 'اجراءات', 'نموذج', 'مسودة',
            'اجتماع', 'محضر', 'بريد', 'خطاب', 'مذكرة', 'نظام', 'دخول',
            'كلمة', 'سر', 'حساب', 'طلب', 'دعم', 'ترجمة', 'ملف',
        ),
    ),
    ScopeDomain(
        id='legal_governance',
        label_en='Legal, governance & procurement',
        label_ar='القانوني والحوكمة والمشتريات',
        terms_en=(
            'legal', 'law', 'contract', 'contracts', 'tender', 'procurement',
            'purchase', 'vendor', 'supplier', 'board', 'committee',
            'governance', 'risk', 'framework', 'agreement',
        ),
        terms_ar=(
            'قانون', 'عقد', 'عقود', 'مناقصة', 'مشتريات', 'شراء', 'مورد',
            'مجلس', 'لجنة', 'حوكمة', 'مخاطر', 'اطار', 'اتفاقية',
        ),
    ),
)

_EN_WORD = re.compile(r'[a-z0-9]+')


@dataclass
class DomainMatch:
    domain_id: str
    domain_label: str
    matched_terms: list[str] = field(default_factory=list)


def _arabic_root(term: str) -> str:
    """Reduce an Arabic term to a matchable stem.

    Strips the definite article, leading conjunctions, and trailing
    plural/pronoun suffixes. This is intentionally crude: it only needs to be
    *recall-friendly*, because a false "in scope" verdict merely means the
    prompt proceeds to the model.
    """
    term = strip_arabic_diacritics(normalize(term))
    term = term.replace('ـ', '')
    for prefix in ('وال', 'بال', 'كال', 'فال', 'لل', 'ال'):
        if term.startswith(prefix) and len(term) - len(prefix) >= 3:
            term = term[len(prefix) :]
            break
    for suffix in ('يات', 'ات', 'ون', 'ين', 'ان', 'ها', 'هم', 'ية', 'ه', 'ي'):
        if term.endswith(suffix) and len(term) - len(suffix) >= 3:
            term = term[: -len(suffix)]
            break
    return term


def _english_terms(text: str) -> set[str]:
    return set(_EN_WORD.findall(text.lower()))


def match_scope(text: str, domains: tuple[ScopeDomain, ...] = DEFAULT_DOMAINS) -> list[DomainMatch]:
    """Return every CBO business domain signalled by *text*."""
    normalized = normalize(text)
    if not normalized:
        return []

    words = _english_terms(normalized)
    haystack_ar = strip_arabic_diacritics(normalized)
    matches: list[DomainMatch] = []

    for domain in domains:
        hits: list[str] = []
        for term in domain.terms_en:
            term_norm = term.lower().strip()
            if not term_norm:
                continue
            if ' ' in term_norm:
                if term_norm in normalized.lower():
                    hits.append(term)
            elif term_norm in words:
                hits.append(term)
        if domain.terms_ar:
            for term in domain.terms_ar:
                root = _arabic_root(term)
                if len(root) >= 3 and root in haystack_ar:
                    hits.append(term)
        if hits:
            matches.append(
                DomainMatch(
                    domain_id=domain.id,
                    domain_label=domain.label_en,
                    matched_terms=sorted(set(hits))[:6],
                )
            )
    return matches


def evaluate_scope(
    text: str,
    domains: tuple[ScopeDomain, ...],
    *,
    strict: bool,
) -> Verdict:
    """L4 verdict for business scope.

    *strict=False* (recommended for rollout): scope never blocks; it only
    records which domain the prompt belongs to, and unscoped prompts pass.
    *strict=True*: a prompt with no CBO business signal is rejected as
    ``off_topic``. Only enable once shadow-mode data shows the allowlist
    covers real traffic.
    """
    if not strict:
        return Verdict(layer=Layer.SCOPE)

    matches = match_scope(text, domains)
    if matches:
        return Verdict(layer=Layer.SCOPE, score=1.0, detail=','.join(m.domain_id for m in matches))

    return Verdict(
        action='block',
        category='off_topic',
        layer=Layer.SCOPE,
        score=1.0,
        rule='scope.no_domain_match',
        detail='no CBO business signal in prompt',
    )


def parse_domains(raw: list[dict] | None) -> tuple[ScopeDomain, ...]:
    """Build domains from admin-supplied config, falling back to defaults."""
    if not raw:
        return DEFAULT_DOMAINS
    domains: list[ScopeDomain] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        domain_id = str(item.get('id') or '').strip()
        if not domain_id:
            continue
        terms_en = item.get('terms_en') or []
        terms_ar = item.get('terms_ar') or []
        if isinstance(terms_en, str):
            terms_en = [t.strip() for t in terms_en.split('|')]
        if isinstance(terms_ar, str):
            terms_ar = [t.strip() for t in terms_ar.split('|')]
        domains.append(
            ScopeDomain(
                id=domain_id,
                label_en=str(item.get('label_en') or domain_id),
                label_ar=str(item.get('label_ar') or domain_id),
                terms_en=tuple(t for t in terms_en if t),
                terms_ar=tuple(t for t in terms_ar if t),
            )
        )
    return tuple(domains) or DEFAULT_DOMAINS


__all__ = [
    'DEFAULT_DOMAINS',
    'DomainMatch',
    'ScopeDomain',
    'evaluate_scope',
    'has_arabic',
    'match_scope',
    'parse_domains',
]
