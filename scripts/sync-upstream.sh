#!/usr/bin/env bash
#
# CBO AI - Upstream Synchronization Pipeline (Bash)
#
set -e

echo "====================================================="
echo "  CBO AI - Upstream Synchronization Pipeline         "
echo "====================================================="

# 1. Check working directory status
if [ -n "$(git status --porcelain)" ]; then
    echo "[!] Working tree has uncommitted changes. Please commit or stash first."
    exit 1
fi

# 2. Verify upstream remote exists
if ! git remote | grep -q "^upstream$"; then
    echo "[*] Adding upstream remote..."
    git remote add upstream https://github.com/open-webui/open-webui.git
fi

# 3. Fetch upstream
echo "[*] Fetching latest changes from upstream..."
git fetch upstream

# 4. Update local main
echo "[*] Updating local 'main' branch..."
git checkout main
git merge --ff-only upstream/main

# 5. Push main to fork
echo "[*] Pushing updated 'main' to origin..."
git push origin main

# 6. Switch back to custom branch and merge main
echo "[*] Merging upstream updates into 'custom' branch..."
git checkout custom

if ! git merge main -m "Sync upstream/main into custom"; then
    echo "[!] Checking for conflicts..."
    # Auto-resolve static assets in favor of CBO branding
    CONFLICTS=$(git diff --name-only --diff-filter=U)
    for file in $CONFLICTS; do
        if [[ "$file" == static/* ]] || [[ "$file" == *.webmanifest ]]; then
            echo "    Auto-resolving CBO asset: $file (keeping ours)"
            git checkout --ours -- "$file"
            git add "$file"
        fi
    done

    REMAINING=$(git diff --name-only --diff-filter=U)
    if [ -z "$REMAINING" ]; then
        git commit -m "Sync upstream/main into custom (resolved brand assets)"
        echo "[+] All asset conflicts resolved automatically!"
    else
        echo "[X] Unresolved code conflicts detected in:"
        echo "$REMAINING"
        echo "Please resolve remaining code conflicts manually, then run: git commit"
        exit 1
    fi
fi

# 7. Ensure CBO branding assets are intact
if [ -f "scripts/setup-cbo-branding.py" ]; then
    python3 scripts/setup-cbo-branding.py || python scripts/setup-cbo-branding.py
fi

# 8. Push custom to origin
echo "[*] Pushing updated 'custom' branch to origin..."
git push origin custom

echo "====================================================="
echo "  Synchronization completed successfully!             "
echo "====================================================="
