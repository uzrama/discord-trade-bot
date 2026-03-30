#!/bin/bash
set -e

echo "🚀 Starting Discord Trade Bot..."

# Wait for Redis to be ready
if [ -n "$REDIS_HOST" ]; then
    echo "⏳ Waiting for Redis at $REDIS_HOST:$REDIS_PORT..."
    
    max_attempts=30
    attempt=0
    
    while ! nc -z "$REDIS_HOST" "$REDIS_PORT"; do
        attempt=$((attempt + 1))
        if [ $attempt -ge $max_attempts ]; then
            echo "❌ Redis is not available after $max_attempts attempts"
            exit 1
        fi
        echo "   Attempt $attempt/$max_attempts - Redis not ready yet..."
        sleep 1
    done
    
    echo "✅ Redis is ready!"
fi

# Create data directory if it doesn't exist
mkdir -p /app/data

# Print environment info
echo "📋 Environment:"
echo "   - Python: $(python --version)"
echo "   - Working directory: $(pwd)"
echo "   - User: $(whoami)"
echo "   - Service type: ${SERVICE_TYPE:-unknown}"

# Execute the command
echo "🎯 Executing: $@"
exec "$@"
