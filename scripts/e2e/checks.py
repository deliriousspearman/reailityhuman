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
    "ftp": [{"options": {}, "checks": [("tcp", 21)]}],
    "desktop": [{"options": {}, "checks": [("tcp", 3389)]}],
    "iis": [{"options": {}, "checks": [("http", "http", 80, "/", None)]}],
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


def base_checks(family: str, access: list[str], name: str) -> list[tuple]:
    """What every machine gets: it answers where its template says it does, under its own name."""
    checks: list[tuple] = []
    if "ssh" in access:
        checks.append(("ssh", "hostname", name))
    if "rdp" in access:
        checks.append(("tcp", 3389))
    return checks
