# 2026-03-02 Server Preparation Log

## Target
- Host: `34.101.230.107`
- User: `lianping1230`

## Commands To Run

```bash
hostname
whoami
python3 --version
sudo ss -lntup '( sport = :80 or sport = :443 )'
sudo systemctl list-unit-files --type=service | egrep 'nginx|apache2|caddy|traefik|haproxy' || true
```

```bash
for s in nginx apache2 caddy traefik haproxy; do
  sudo systemctl stop "$s" 2>/dev/null || true
  sudo systemctl disable "$s" 2>/dev/null || true
done
sudo ss -lntup '( sport = :80 or sport = :443 )'
```

## Result
- Fill this section with real outputs from server execution.

