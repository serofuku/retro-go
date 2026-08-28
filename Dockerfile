FROM espressif/idf:release-v4.4

WORKDIR /app

ADD . /app

# Install FAT filesystem tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        dosfstools \
        mtools && \
    rm -rf /var/lib/apt/lists/*

# Apply patches
RUN cd /opt/esp/idf && \
    patch --ignore-whitespace -p1 -i "/app/tools/patches/panic-hook (esp-idf 4).diff" && \
    patch --ignore-whitespace -p1 -i "/app/tools/patches/sdcard-fix (esp-idf 4).diff"

# Create 8 MB FAT VFS image
RUN truncate -s 8M /app/vfs.img && \
    mkfs.fat -F 16 -n RETROGO /app/vfs.img

# Create Retro-Go directories
RUN mmd -i /app/vfs.img ::/roms && \
    mmd -i /app/vfs.img ::/roms/gbc && \
    mmd -i /app/vfs.img ::/retro-go && \
    mmd -i /app/vfs.img ::/retro-go/config && \
    mmd -i /app/vfs.img ::/retro-go/saves && \
    mmd -i /app/vfs.img ::/retro-go/states && \
    mmd -i /app/vfs.img ::/retro-go/bios

# Copy all GBC ROMs into the internal-flash filesystem
RUN if compgen -G "/app/roms/gbc/*.gbc" > /dev/null; then \
        mcopy -i /app/vfs.img /app/roms/gbc/*.gbc ::/roms/gbc/; \
    else \
        echo "WARNING: No .gbc ROMs found"; \
    fi

# Show what was put into the filesystem
RUN echo "=== VFS contents ===" && \
    mdir -i /app/vfs.img ::/roms/gbc

# Build complete ESP32-S3 image
SHELL ["/bin/bash", "-c"]

RUN . /opt/esp/idf/export.sh && \
    python rg_tool.py \
        --target=esp32-s3-devkit \
        --fatsize=8M \
        build-img

RUN echo "=== FINAL IMAGE ===" && \
    ls -lh /app/*.img
