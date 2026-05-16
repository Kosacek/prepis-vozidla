set -e
CONF=/share/Container/spznaklic/nginx-conf/default.conf
VHOST=/share/Container/zadosti/source/docker/nginx-zadosti.conf
TS=$(date +%Y%m%d-%H%M%S)

echo "=== verify zadosti-app on shared net ==="
docker network inspect spznaklic-web_default --format '{{range .Containers}}{{.Name}} {{end}}' | tr ' ' '\n' | grep -x zadosti-app && echo "  on spznaklic-web_default: OK"

echo "=== idempotency check ==="
if grep -q "zadosti.spznaklic.cz" "$CONF"; then
  echo "  vhost already present — skipping append"
else
  echo "=== backup default.conf -> default.conf.bak-$TS ==="
  cp "$CONF" "$CONF.bak-$TS"
  echo "=== append zadosti vhost ==="
  printf '\n# --- zadosti (prepisy vozidel) ---\n' >> "$CONF"
  cat "$VHOST" >> "$CONF"
  echo "  appended ($(wc -l < "$CONF") lines total)"
fi

echo "=== nginx -t (validate) ==="
if docker exec spznaklic_nginx nginx -t 2>&1; then
  echo "=== nginx -s reload ==="
  docker exec spznaklic_nginx nginx -s reload 2>&1
  echo "  RELOAD OK"
else
  echo "  !! nginx -t FAILED — restoring backup, NOT reloading"
  LATEST=$(ls -t "$CONF".bak-* 2>/dev/null | head -1)
  if [ -n "$LATEST" ]; then cp "$LATEST" "$CONF"; echo "  restored from $LATEST"; fi
  exit 1
fi

echo "=== confirm other sites still in config ==="
grep -c "server_name" "$CONF"
grep -oE "server_name[^;]+" "$CONF"
