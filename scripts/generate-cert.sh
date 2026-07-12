#!/bin/bash
# Erzeugt eine lokale CA + ein davon signiertes TLS-Server-Zertifikat, das die
# Anforderungen von Apple (macOS/iOS) an Server-Zertifikate erfuellt. Grund:
# Ein einzelnes selbstsigniertes Zertifikat, das gleichzeitig als eigener
# Trust-Anchor UND als Server-Leaf dient, scheitert auf modernem macOS an
# trustd ("Leaf has invalid basic constraints") und wird vom Kontakte-Sync-
# Daemon (dataaccessd/contactsd) still abgelehnt - iOS umgeht das nur, weil man
# dort das Zertifikat per Dialog manuell bestaetigt. Siehe docs/konzept.md Abschnitt 9.
#
# Apple-Anforderungen an das Leaf (support.apple.com/en-us/HT211025 u. a.):
#   - Subject Alternative Name (SAN) mit dem Hostnamen  (CN wird ignoriert)
#   - basicConstraints: CA:FALSE
#   - extendedKeyUsage: serverAuth
#   - Gueltigkeit <= 398 Tage
#   - SHA-256, RSA >= 2048
# Die CA selbst darf laenger gueltig sein und muss auf jedem Client einmalig als
# vertrauenswuerdig markiert werden (siehe Ausgabe am Ende).
#
# Aufruf: scripts/generate-cert.sh <TLS_DIR> <HOSTNAME.local>
set -euo pipefail

TLS_DIR="${1:?TLS-Zielverzeichnis fehlt}"
HOSTNAME_LOCAL="${2:?Hostname (z.B. Fabio-Mac-Studio.local) fehlt}"

mkdir -p "$TLS_DIR"
CA_KEY="$TLS_DIR/ca-key.pem"
CA_CERT="$TLS_DIR/ca-cert.pem"
LEAF_KEY="$TLS_DIR/key.pem"
LEAF_CERT="$TLS_DIR/cert.pem"
LEAF_CSR="$TLS_DIR/leaf.csr"
LEAF_ONLY="$TLS_DIR/leaf-cert.pem"

# 1) Lokale CA (10 Jahre gueltig, echtes CA-Zertifikat). Nur der oeffentliche
#    Teil (ca-cert.pem) wird verteilt; ca-key.pem bleibt lokal und geheim.
/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CA_KEY" -out "$CA_CERT" \
  -days 3650 -sha256 -subj "/CN=Rubrica Local CA ($HOSTNAME_LOCAL)" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
chmod 600 "$CA_KEY"

# 2) Leaf-Schluessel + Zertifikatsanforderung.
/usr/bin/openssl req -newkey rsa:2048 -nodes \
  -keyout "$LEAF_KEY" -out "$LEAF_CSR" \
  -subj "/CN=$HOSTNAME_LOCAL" 2>/dev/null
chmod 600 "$LEAF_KEY"

# 3) Extension-Datei fuer das Leaf (Apple-konform).
EXT_FILE="$(mktemp)"
cat > "$EXT_FILE" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:$HOSTNAME_LOCAL,DNS:localhost,IP:127.0.0.1
EOF

# 4) Leaf von der CA signieren, 397 Tage (< 398-Tage-Grenze von Apple).
/usr/bin/openssl x509 -req -in "$LEAF_CSR" \
  -CA "$CA_CERT" -CAkey "$CA_KEY" -CAcreateserial \
  -days 397 -sha256 -extfile "$EXT_FILE" -out "$LEAF_ONLY" 2>/dev/null

# 5) Radicale bekommt die Full-Chain (Leaf + CA) als cert.pem, damit Clients die
#    Kette auch ohne lokal installierte CA aufbauen koennen; key.pem ist der Leaf-Key.
cat "$LEAF_ONLY" "$CA_CERT" > "$LEAF_CERT"

rm -f "$LEAF_CSR" "$EXT_FILE"

echo "Zertifikat erzeugt:"
echo "  CA (auf jedem Client als vertrauenswuerdig markieren): $CA_CERT"
echo "  Server-Zertifikat (Full-Chain, fuer Radicale):         $LEAF_CERT"
echo "  Server-Schluessel:                                     $LEAF_KEY"
