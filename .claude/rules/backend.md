# Backend Development Rules

## Docker Container

- Use 'docker/compose/automations/{dockername}/compose.yml' for development
- Use 'docker/compose/automations/{dockername}/Dockerfile' for custom container setup
- Use 'docker/compose/automations/{dockername}/.env' for container-specific environment variables
- All files belonging to the container are located in the same directory as the Dockerfile
- Expand 'STACKS' in 'docker/compose/scripts/Makefile' to add new containers
- Use 'docker/compose/scripts/Makefile' for common commands (build, up, down, logs)
- Use ./sync-compose.sh' to sync compose files to project root

## Database (postgresql)

- ALWAYS enable Row Level Security on every table
- Create RLS policies for SELECT, INSERT, UPDATE, DELETE
- Add indexes on columns used in WHERE, ORDER BY, and JOIN clauses
- Use foreign keys with ON DELETE CASCADE where appropriate
- Never skip RLS - security first

## API Routes

- Validate all inputs using Zod schemas before processing
- Always check authentication: verify user session exists
- Return meaningful error messages with appropriate HTTP status codes
- Use `.limit()` on all list queries

## Query Patterns

- Use postgresql joins instead of N+1 query loops
- Use `unstable_cache` from Next.js for rarely-changing data
- Always handle errors from postgresql responses

## Security

- Never hardcode secrets in source code
- Use environment variables for all credentials
- Validate and sanitize all user input
- Use parameterized queries (postgresql handles this)
