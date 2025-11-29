#!/bin/bash
# Script om Hummingbot wachtwoord te wijzigen

# Hummingbot gebruikt de conf directory in de repository root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_DIR="${REPO_ROOT}/conf"
PASSWORD_FILE="${CONF_DIR}/.password_verification"

echo "=========================================="
echo "  HUMMINGBOT WACHTWOORD WIJZIGEN"
echo "=========================================="
echo ""

# Check of password file bestaat
if [ ! -f "$PASSWORD_FILE" ]; then
    echo "⚠️  Geen wachtwoord gevonden op: $PASSWORD_FILE"
    echo "   Dit betekent dat er nog geen wachtwoord is ingesteld."
    echo "   Start Hummingbot en stel een wachtwoord in."
    exit 1
fi

echo "📁 Password file gevonden: $PASSWORD_FILE"
echo ""
echo "⚠️  BELANGRIJK:"
echo "   - Dit verwijdert het huidige wachtwoord"
echo "   - Bij de volgende start van Hummingbot moet je een NIEUW wachtwoord instellen"
echo "   - Je oude wachtwoord werkt NIET meer"
echo ""
read -p "Wil je doorgaan? (ja/nee): " confirm

if [ "$confirm" != "ja" ]; then
    echo "❌ Geannuleerd."
    exit 0
fi

# Backup maken
BACKUP_FILE="${PASSWORD_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$PASSWORD_FILE" "$BACKUP_FILE"
echo "✅ Backup gemaakt: $BACKUP_FILE"

# Verwijder password file
rm "$PASSWORD_FILE"
echo "✅ Password file verwijderd"
echo ""
echo "=========================================="
echo "  ✅ KLAAR!"
echo "=========================================="
echo ""
echo "📋 Volgende stappen:"
echo "   1. Start Hummingbot: bin/hummingbot.py"
echo "   2. Je wordt gevraagd om een NIEUW wachtwoord in te stellen"
echo "   3. Voer je nieuwe wachtwoord 2x in"
echo ""
echo "💡 Tip: Als je je oude wachtwoord terug wilt:"
echo "   mv $BACKUP_FILE $PASSWORD_FILE"
echo ""
