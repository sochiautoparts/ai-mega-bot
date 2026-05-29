# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in GitMoji AI, please report it privately:

1. **Do NOT** create a public GitHub issue
2. Email: security@gitmoji-ai.dev
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if you have one)

## Security Best Practices

### API Keys

- **Never** commit your OpenAI API key to version control
- Use environment variables or `.env` files
- Add `.env` to `.gitignore` (done automatically by `gmai init`)

### License Keys

- Pro license keys are stored locally in `~/.gitmoji-ai/`
- Keys are never transmitted to third parties
- Validation happens against our API server

### Data Privacy

- GitMoji AI only reads git diffs when you run a command
- No data is stored or transmitted except to OpenAI for AI generation
- Usage tracking is stored locally only
- We do not collect personal information
