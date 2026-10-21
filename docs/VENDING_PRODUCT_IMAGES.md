# Vending product images

M-Group supports one optional primary image per Vending product slot (Product ID 1–5).

- Upload formats: JPEG, PNG, and WebP.
- Maximum uploaded file size: 2 MiB (2,097,152 bytes).
- Images are decoded and validated server-side; images with invalid content or dimensions above 4096 × 4096 are rejected.
- Image bytes and MIME type are stored in SQLite with the product record, so native database backups include them.
- The admin WebUI provides a preview and an **Upload gambar** button on each product row, beside the image. Name, price, stock, and slot capacity are editable directly in that row and can be saved without opening the separate product form. The separate form remains available for initial product setup and image deletion.
- The vending catalog API returns an image_url when a product has an image. Vending firmware can request that URL with the same X-M-Group-Device-Key header used for the catalog API.
- Image responses use the stored validated MIME type and X-Content-Type-Options: nosniff.

Catalog endpoint: GET /api/v1/vending/{machine_id}/products

Image endpoint: GET /api/v1/vending/{machine_id}/products/{product_id}/image

Admin upload endpoint: PUT /api/v1/vending/{machine_id}/products/{product_id}/image using multipart form field image.

Admin delete endpoint: DELETE /api/v1/vending/{machine_id}/products/{product_id}/image.

The API and WebUI support is implemented here. Actual LCD rendering and image decoding on ESP32 firmware must be implemented and verified with the final screen model and its resolution/available RAM.
