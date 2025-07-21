# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a Vulnerability

We take the security of AegisIPC seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### Please do NOT:
- Open a public GitHub issue
- Post about it on social media
- Exploit the vulnerability for any purpose other than testing

### Please DO:
- Email us at: security@aegisipc.com
- Include the following information:
  - Type of vulnerability (e.g., buffer overflow, SQL injection, cross-site scripting, etc.)
  - Full paths of source file(s) related to the vulnerability
  - The location of the affected source code (tag/branch/commit or direct URL)
  - Step-by-step instructions to reproduce the issue
  - Proof-of-concept or exploit code (if possible)
  - Impact of the issue, including how an attacker might exploit it

### What to expect:
- We will acknowledge receipt of your vulnerability report within 48 hours
- We will provide a more detailed response within 7 days
- We will work on fixing the vulnerability and coordinate a release date with you
- We will publicly acknowledge your responsible disclosure (unless you prefer to remain anonymous)

## Security Best Practices

When contributing to AegisIPC, please follow these security best practices:

### Code Security
1. **Never commit secrets**: Use environment variables for sensitive data
2. **Validate all inputs**: Always validate and sanitize user inputs
3. **Use parameterized queries**: Prevent SQL injection attacks
4. **Implement proper authentication**: Use strong authentication mechanisms
5. **Apply least privilege**: Grant minimum necessary permissions
6. **Handle errors gracefully**: Don't expose sensitive information in error messages

### Dependencies
1. **Keep dependencies updated**: Regularly update to patch known vulnerabilities
2. **Review dependencies**: Audit new dependencies before adding them
3. **Use dependency scanning**: Our CI runs safety, pip-audit, and Trivy scans
4. **Pin versions**: Always pin dependency versions for reproducibility

### Development Process
1. **Code review**: All code must be reviewed before merging
2. **Security scanning**: All PRs must pass security scans
3. **Test security**: Include security test cases
4. **Document security**: Document security considerations in code

## Security Tools

We use the following tools to maintain security:

- **Bandit**: Python AST security scanner
- **Safety**: Dependency vulnerability scanner
- **pip-audit**: Python package vulnerability scanner
- **Trivy**: Container vulnerability scanner
- **pre-commit hooks**: Automated security checks before commit

## Running Security Checks Locally

```bash
# Run all security checks
uv run bandit -r packages/
uv run safety check
uv run pip-audit

# Run pre-commit hooks
uv run pre-commit run --all-files
```

## Security Updates

Security updates will be released as soon as possible after a vulnerability is confirmed. We will:

1. Release a patch version fixing the vulnerability
2. Update the security advisory with details
3. Notify users through our communication channels

Thank you for helping keep AegisIPC secure!
