#!/bin/bash
# Health check script for Discord Trade Bot services
# Returns 0 if service is healthy, 1 otherwise

SERVICE_TYPE="${SERVICE_TYPE:-unknown}"

case "$SERVICE_TYPE" in
  discord)
    # Check if Discord bot process is running
    if pgrep -f "discord-trade-bot discord" > /dev/null; then
      exit 0
    else
      echo "Discord bot process not found"
      exit 1
    fi
    ;;
    
  tracker)
    # Check if tracker process is running
    if pgrep -f "discord-trade-bot tracker" > /dev/null; then
      exit 0
    else
      echo "Tracker process not found"
      exit 1
    fi
    ;;
    
  worker)
    # Check if taskiq worker process is running
    if pgrep -f "taskiq worker" > /dev/null; then
      exit 0
    else
      echo "Worker process not found"
      exit 1
    fi
    ;;
    
  *)
    echo "Unknown service type: $SERVICE_TYPE"
    exit 1
    ;;
esac
