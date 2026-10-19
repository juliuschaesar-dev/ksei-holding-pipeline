import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = os.environ["SUPERSET_DATABASE_URI"]

FEATURE_FLAGS = {
    # The "Change since peak" card compares with the highest share of the whole market, which is a
    # subquery. Only admins edit charts here; the ClickHouse user reads the gold database only.
    "ALLOW_ADHOC_SUBQUERY": True,
}

# Values are rupiah and the dashboard counts them in trillions: the format `$,.0f` of a value
# divided by 10**12 reads "8,009 T". (An SI format would call 8,009 trillion "8.0P".)
D3_FORMAT = {"decimal": ".", "thousands": ",", "grouping": [3], "currency": ["", " T"]}

# A Handlebars chart compiles its template in the browser, which needs `unsafe-eval`. The rest of
# Superset's content security policy stays as it is (scripts still need the page's nonce).
from superset.config import TALISMAN_CONFIG  # noqa: E402

TALISMAN_CONFIG["content_security_policy"]["script-src"].append("'unsafe-eval'")

# Superset strips `style` attributes from the HTML of Markdown and Handlebars charts. The cards need
# them for their typography; this allows that attribute only (no <style> tags, no scripts).
HTML_SANITIZATION_SCHEMA_EXTENSIONS = {"attributes": {"*": ["style"]}}
