CREATE UNIQUE INDEX IF NOT EXISTS ux_vending_machine_device
ON vending_machines(hardware_id) WHERE hardware_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_vending_machines_status
ON vending_machines(status);

CREATE UNIQUE INDEX IF NOT EXISTS ux_vending_product_machine_slot
ON vending_products(machine_id,slot) WHERE slot IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_vending_products_machine_slot
ON vending_products(machine_id,slot);