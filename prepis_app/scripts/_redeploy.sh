set -e
cd /share/Container/zadosti
echo "=== build (--no-cache --pull) ==="
docker compose -f docker-compose.nas.yml build --no-cache --pull 2>&1 | tail -8
echo "=== up -d ==="
docker compose -f docker-compose.nas.yml up -d 2>&1 | tail -5
sleep 8
echo "=== status ==="
docker inspect --format 'health={{.State.Health.Status}} restart={{.HostConfig.RestartPolicy.Name}}' zadosti-app
docker logs --tail 6 zadosti-app
