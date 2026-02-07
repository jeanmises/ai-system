#!/bin/bash
# Script per ottenere JWT token da Keycloak

echo "🔑 Ottengo token da Keycloak..."

RESPONSE=$(curl -s -X POST 'http://localhost:8080/realms/ai-system/protocol/openid-connect/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=password&client_id=ai-system-api&username=testuser&password=testpass123')

# Estrai access_token
TOKEN=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))")

if [ -z "$TOKEN" ]; then
    echo "❌ Errore nell'ottenere il token!"
    echo "$RESPONSE" | python3 -m json.tool
    exit 1
fi

# Salva token
echo "$TOKEN" > .test_token

echo "✅ Token ottenuto e salvato in .test_token"
echo ""
echo "📋 Info token:"
echo "$TOKEN" | cut -d '.' -f 2 | python3 -c "
import sys, base64, json
payload = sys.stdin.read().strip()
padding = len(payload) % 4
if padding: payload += '=' * (4 - padding)
data = json.loads(base64.b64decode(payload))
print(f\"  Username: {data['preferred_username']}")
print(f\"  Email: {data['email']}")
print(f\"  Expires in: 3600 seconds (1 hour)\")
"

echo ""
echo "💡 Usa il token così:"
echo "   export TOKEN=\$(cat .test_token)"
echo "   curl -H \"Authorization: Bearer \$TOKEN\" http://localhost:8000/sessions"
