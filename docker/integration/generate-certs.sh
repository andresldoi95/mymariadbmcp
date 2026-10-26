#!/bin/sh
set -eu

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout /certs/ca-key.pem \
  -out /certs/ca.pem \
  -days 2 \
  -subj "/CN=MariaDB MCP disposable test CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

openssl req -newkey rsa:2048 -nodes \
  -keyout /certs/server-key.pem \
  -out /certs/server.csr \
  -subj "/CN=mariadb"

cat > /certs/server-ext.cnf <<'EOF'
subjectAltName=DNS:mariadb,IP:127.0.0.1
basicConstraints=critical,CA:FALSE
extendedKeyUsage=serverAuth
keyUsage=digitalSignature,keyEncipherment
EOF

openssl x509 -req \
  -in /certs/server.csr \
  -CA /certs/ca.pem \
  -CAkey /certs/ca-key.pem \
  -CAcreateserial \
  -out /certs/server-cert.pem \
  -days 2 \
  -extfile /certs/server-ext.cnf

chmod 644 /certs/ca.pem /certs/server-cert.pem /certs/server-key.pem
