#!/bin/bash

echo "Building custom sandbox image for Matplotlib support..."
podman build -t cowork-sandbox -f Dockerfile.sandbox .

if [ $? -eq 0 ]; then
    echo "✅ Success! 'cowork-sandbox' image is ready."
else
    echo "❌ Build Failed. Check the error above."
fi
