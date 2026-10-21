"""What the end-to-end tests check on a deployed machine, per extra (run.py uses these).

Each extra has one or more cases: options to deploy it with, and checks to run once it's ready.
Checks are tuples:
  ("tcp", port)                              the port accepts connections
  ("http", scheme, port, path, text)         answers 2xx/3xx, and the page has `text` (or None)
  ("ssh", command, expected)                 run on the machine as its user (Windows: PowerShell);
                                             the output, stripped, must contain `expected`
Commands can use {ip}, {username} and {password} (single-quote-safe for sh, and for PowerShell).
An extra not listed here only gets the checks every machine gets.
"""

CHINOOK_TRACKS = "3503"

CASES: dict[str, list[dict]] = {
    "nginx": [{"options": {}, "checks": [("http", "http", 80, "/", None)]}],
    "apache": [{"options": {}, "checks": [("http", "http", 80, "/", None)]}],
    "apache-https": [{"options": {}, "checks": [("http", "https", 443, "/", None), ("tcp", 80)]}],
    "wordpress": [
        {"options": {}, "checks": [("http", "http", 80, "/", "wp-content")]},
        {"options": {"https": "yes"}, "checks": [("http", "https", 443, "/", "wp-content")]},
    ],
    "nextcloud": [
        {"options": {}, "checks": [("http", "http", 80, "/status.php", '"installed":true')]},
        {"options": {"https": "yes"}, "checks": [("http", "https", 443, "/status.php", '"installed":true')]},
    ],
    "nextcloud-snap": [{"options": {}, "checks": [("http", "http", 80, "/status.php", '"installed":true')]}],
    "postgresql": [
        {
            "options": {"sample_data": "yes"},
            "checks": [
                ("tcp", 5432),
                ("ssh", "PGPASSWORD={password} psql -h {ip} -U {username} -d chinook -tAc 'SELECT count(*) FROM track'", CHINOOK_TRACKS),
            ],
        }
    ],
    "mariadb": [
        {
            "options": {"sample_data": "yes"},
            "checks": [
                ("tcp", 3306),
                ("ssh", "mariadb -h {ip} -u {username} -p{password} -N -e 'SELECT count(*) FROM Chinook.Track'", CHINOOK_TRACKS),
            ],
        }
    ],
    "mysql": [
        {
            "options": {"sample_data": "yes"},
            "checks": [
                ("tcp", 3306),
                ("ssh", "mysql -h {ip} -u {username} -p{password} -N -e 'SELECT count(*) FROM Chinook.Track' 2>/dev/null", CHINOOK_TRACKS),
            ],
        }
    ],
    "sqlite": [{"options": {"sample_data": "yes"}, "checks": [("ssh", "sqlite3 ~/chinook.db 'SELECT count(*) FROM Track'", CHINOOK_TRACKS)]}],
    "mail": [{"options": {}, "checks": [("tcp", 25), ("tcp", 143), ("tcp", 587), ("tcp", 993), ("http", "http", 80, "/", "Roundcube")]}],
    # Full mail servers: webmail, and the user's mailbox over IMAP with the machine's password.
    "iredmail": [
        {
            "options": {"users": "alice"},
            "checks": [
                ("tcp", 25), ("tcp", 587), ("tcp", 993),
                ("http", "https", 443, "/mail/", "Roundcube"),
                ("http", "https", 443, "/iredadmin/", "iRedAdmin"),
                ("ssh", "curl -sk imaps://127.0.0.1/ -u {username}@lab.example:{password}", "INBOX"),
                ("ssh", "curl -sk imaps://127.0.0.1/ -u alice@lab.example:{password}", "INBOX"),
            ],
        }
    ],
    "zimbra": [
        {
            "options": {"users": "alice"},
            "checks": [
                ("tcp", 25), ("tcp", 993), ("tcp", 7071),
                ("http", "https", 443, "/", "Zimbra"),
                ("ssh", "curl -sk imaps://127.0.0.1/ -u {username}@lab.example:{password}", "INBOX"),
                ("ssh", "curl -sk imaps://127.0.0.1/ -u alice@lab.example:{password}", "INBOX"),
            ],
        }
    ],
    "ftp": [{"options": {}, "checks": [("tcp", 21)]}],
    "minio": [
        {
            "options": {"bucket": "e2e"},
            "checks": [
                ("http", "http", 9000, "/minio/health/live", None),
                ("http", "http", 9001, "/", "MinIO Console"),
                ("ssh", "mc ls lab", "e2e/"),
                ("ssh", "mc admin info lab", "online"),
            ],
        }
    ],
    # The servers on their own (their agents are checked by deploying a pair: they need the server's machine).
    "wazuh": [
        {
            "options": {},
            "checks": [
                ("tcp", 1514), ("tcp", 1515),
                ("http", "https", 443, "/app/login", None),
                ("ssh", "curl -sk -u {username}:{password} https://127.0.0.1:9200/_plugins/_security/authinfo", '"backend_roles":["admin"]'),
            ],
        }
    ],
    "zabbix": [
        {
            "options": {},
            "checks": [
                ("tcp", 10051),
                ("http", "http", 80, "/zabbix/", "Zabbix"),
                (
                    "ssh",
                    "curl -s -H 'Content-Type: application/json-rpc' http://127.0.0.1/zabbix/api_jsonrpc.php"
                    " -d '{\"jsonrpc\":\"2.0\",\"method\":\"user.login\",\"params\":{\"username\":\"{username}\",\"password\":\"{password}\"},\"id\":1}'",
                    '"result":"',
                ),
            ],
        }
    ],
    "python": [
        {"options": {"version": "3.15"}, "checks": [("ssh", "python3.15 -c 'import ssl, sys; print(sys.version)'", "3.15.0")]},
        {"options": {"version": "3.8"}, "checks": [("ssh", "pip3.8 --version", "python 3.8")]},
        {
            "options": {"version": "2.7", "make_default": "yes"},
            "checks": [("ssh", "python --version 2>&1; python -c 'import ssl; print(ssl.OPENSSL_VERSION)'", "Python 2.7.18"), ("ssh", "pip2 --version", "python 2.7")],
        },
    ],
    "desktop": [{"options": {}, "checks": [("tcp", 3389)]}],
    "iis": [{"options": {}, "checks": [("http", "http", 80, "/", None)]}],
    # Docker and the container apps (their images are in the template; nothing is pulled).
    "docker": [{"options": {}, "checks": [("ssh", "docker info >/dev/null && echo docker-ok", "docker-ok")]}],
    "juice-shop": [{"options": {}, "checks": [("http", "http", 80, "/", "OWASP Juice Shop")]}],
    "dvwa": [{"options": {}, "checks": [("http", "http", 80, "/login.php", "Damn Vulnerable Web Application")]}],
    "uptime-kuma": [{"options": {}, "checks": [("http", "http", 80, "/", "Uptime Kuma")]}],
    "grafana": [
        {
            "options": {},
            "checks": [
                ("http", "http", 80, "/login", "Grafana"),
                ("ssh", "curl -s -u {username}:{password} http://127.0.0.1/api/user", '"isGrafanaAdmin":true'),
            ],
        }
    ],
    "vaultwarden": [{"options": {}, "checks": [("http", "https", 443, "/", "Vaultwarden")]}],
    "gitea": [
        {
            "options": {},
            "checks": [
                ("http", "http", 80, "/", "Gitea"),
                ("tcp", 2222),
                ("ssh", "curl -s -u {username}:{password} http://127.0.0.1/api/v1/user", '"is_admin":true'),
            ],
        }
    ],
    "mssql": [
        {
            "options": {"sample_data": "yes"},
            "checks": [
                ("tcp", 1433),
                (
                    "ssh",
                    "$c = New-Object System.Data.SqlClient.SqlConnection 'Server=localhost;User Id={username};Password={password};TrustServerCertificate=true';"
                    " $c.Open(); $q = $c.CreateCommand(); $q.CommandText = 'SELECT count(*) FROM Chinook.dbo.Track'; $q.ExecuteScalar()",
                    CHINOOK_TRACKS,
                ),
            ],
        }
    ],
    "outlook": [
        {
            "options": {},
            "checks": [("ssh", "Test-Path 'C:\\Program Files\\Microsoft Office\\root\\Office16\\OUTLOOK.EXE'", "True")],
        }
    ],
}


# Systems whose shell has no `hostname`: a command that shows its user signed in, and what it prints.
SIGN_IN_CHECK = {"mikrotik": ("/system identity print", "name")}
# Systems without a POSIX shell: how the lifecycle test leaves a mark before a reset (which must undo
# it), as (command that makes it, command that shows it, text that's there while it is).
RESET_MARKER = {"mikrotik": ("/system identity set name=e2e-marker", "/system identity print", "e2e-marker")}


def base_checks(family: str, access: list[str], name: str, template: str = "") -> list[tuple]:
    """What every machine gets: it answers where its template says it does, under its own name (a
    complete image, family image, keeps its own, so only that its user signs in)."""
    checks: list[tuple] = []
    if "ssh" in access:
        if template in SIGN_IN_CHECK:
            checks.append(("ssh", *SIGN_IN_CHECK[template]))
        else:
            checks.append(("ssh", "hostname", "" if family == "image" else name))
    if "rdp" in access:
        checks.append(("tcp", 3389))
    if "web" in access and family == "image":
        checks.append(("tcp", 80))
    return checks
