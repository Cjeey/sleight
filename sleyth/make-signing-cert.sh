#!/bin/bash
# Create a STABLE self-signed code-signing identity for Sleyth. Run once.
#
# Why you want this:
#   PyInstaller ad-hoc signs every build, and an ad-hoc signature is derived
#   from the bytes. Change one line, rebuild, and macOS sees a DIFFERENT app
#   - so Camera and Accessibility permissions you already granted no longer
#   apply, and it asks again. Every time. Even though the old entry is still
#   sitting in System Settings looking enabled.
#
#   A self-signed certificate gives the app one constant identity. Grant the
#   permissions once and they stick across rebuilds.
#
# This touches your login keychain, so run it yourself and read it first.
# It creates: a certificate named "Sleyth Dev", valid 10 years, code-signing
# only. It cannot sign anything for anyone else and is not trusted by other
# machines - it is purely a local identity.
set -e

if security find-identity -v -p codesigning 2>/dev/null | grep -q "Sleyth Dev"; then
  echo "'Sleyth Dev' already exists - nothing to do."
  exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

cat > cfg.cnf <<'EOF'
[ req ]
distinguished_name = dn
x509_extensions = v3
prompt = no
[ dn ]
CN = Sleyth Dev
[ v3 ]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF

echo "Generating the certificate..."
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
  -days 3650 -nodes -config cfg.cnf >/dev/null 2>&1
openssl pkcs12 -export -inkey key.pem -in cert.pem -out sleyth.p12 \
  -passout pass:sleyth -name "Sleyth Dev" >/dev/null 2>&1

echo "Importing into your login keychain (macOS may ask you to allow it)..."
security import sleyth.p12 -k ~/Library/Keychains/login.keychain-db \
  -P sleyth -T /usr/bin/codesign -A

echo
if security find-identity -v -p codesigning 2>/dev/null | grep -q "Sleyth Dev"; then
  echo "Done. Now run ./install.sh - it will sign with this identity, and"
  echo "the permissions you grant will survive future rebuilds."
else
  echo "The identity was imported but codesign cannot see it yet."
  echo "Open Keychain Access > login > Certificates > 'Sleyth Dev',"
  echo "expand it, and set 'Code Signing' trust to 'Always Trust'."
fi
