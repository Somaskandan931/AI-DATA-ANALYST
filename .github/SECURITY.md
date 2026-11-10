# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private reporting
instead: open the repository's **Security** tab and choose **Report a vulnerability**.

Include what you found, how to reproduce it (a failing question, SQL string or file is ideal),
and the version or commit. You can expect an acknowledgement within a few days.

## In scope

- Ways to make the SQL Analyst execute anything other than a single validated `SELECT`
- Ways to read tables or columns outside the schema allow-list, or to write to a database
- Ways to bypass upload, row, column, timeout or result-size limits
- Leaks of API keys or the app password into pages, errors or logs
- Model output being treated as instructions or as executable code

## Out of scope

- Findings that need a malicious operator (access to the server, its environment or its secrets)
- Denial of service through sheer request volume against a public deployment
- Weaknesses in third-party services such as Gemini or Streamlit Community Cloud

## How AIDA is designed to resist these

See [docs/SECURITY.md](../docs/SECURITY.md) for the threat model and the layered controls.
AIDA is a research and portfolio MVP; put a password in front of any public deployment.
