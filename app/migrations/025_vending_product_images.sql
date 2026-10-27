-- Versioned product image storage. Images are optimized on upload and cached by content hash.
CREATE TABLE IF NOT EXISTS vending_product_images (
    machine_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK(content_type IN ('image/webp','image/jpeg')),
    image_data BLOB NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK(byte_size > 0 AND byte_size <= 2097152),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(machine_id, product_id)
);
CREATE INDEX IF NOT EXISTS ix_vending_product_images_hash ON vending_product_images(sha256);
