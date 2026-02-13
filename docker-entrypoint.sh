#!/bin/bash
set -e

# Fix permissions
echo "Fixing permissions for /app/data..."
chown -R 1000:1000 /app/data || echo "Warning: Failed to chown /app/data"
chmod 777 /app/data || echo "Warning: Failed to chmod /app/data"

if [ -f /app/data/oss_converter.db ]; then
    echo "Fixing permissions for database file..."
    chmod 666 /app/data/oss_converter.db || echo "Warning: Failed to chmod database file"
fi

# Execute command
exec "$@"
