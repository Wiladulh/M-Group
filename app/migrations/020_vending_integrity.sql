-- M-Group database integrity hardening.
-- Triggers are used instead of rebuilding legacy tables so existing installations
-- retain every row while new writes are validated consistently on old and new DBs.

CREATE INDEX IF NOT EXISTS ix_vending_products_machine
    ON vending_products(machine_id);
CREATE INDEX IF NOT EXISTS ix_vending_tx_machine_created
    ON vending_transactions(machine_id, created_at);

CREATE TRIGGER IF NOT EXISTS trg_vending_product_integrity_insert
BEFORE INSERT ON vending_products
BEGIN
    SELECT CASE
        WHEN NEW.price IS NULL OR NEW.price <= 0
        THEN RAISE(ABORT, 'vending_product_price_must_be_positive')
    END;
    SELECT CASE
        WHEN NEW.stock IS NOT NULL AND NEW.stock < 0
        THEN RAISE(ABORT, 'vending_product_stock_must_be_nonnegative')
    END;
    SELECT CASE
        WHEN NEW.machine_id IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM vending_machines WHERE machine_id = NEW.machine_id)
        THEN RAISE(ABORT, 'vending_machine_not_found')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_vending_product_integrity_update
BEFORE UPDATE OF machine_id, price, stock ON vending_products
BEGIN
    SELECT CASE
        WHEN NEW.price IS NULL OR NEW.price <= 0
        THEN RAISE(ABORT, 'vending_product_price_must_be_positive')
    END;
    SELECT CASE
        WHEN NEW.stock IS NOT NULL AND NEW.stock < 0
        THEN RAISE(ABORT, 'vending_product_stock_must_be_nonnegative')
    END;
    SELECT CASE
        WHEN NEW.machine_id IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM vending_machines WHERE machine_id = NEW.machine_id)
        THEN RAISE(ABORT, 'vending_machine_not_found')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_vending_transaction_integrity_insert
BEFORE INSERT ON vending_transactions
BEGIN
    SELECT CASE
        WHEN NEW.amount IS NULL OR NEW.amount < 0
        THEN RAISE(ABORT, 'vending_transaction_amount_must_be_nonnegative')
    END;
    SELECT CASE
        WHEN NOT EXISTS (SELECT 1 FROM vending_machines WHERE machine_id = NEW.machine_id)
        THEN RAISE(ABORT, 'vending_machine_not_found')
    END;
    SELECT CASE
        WHEN NOT EXISTS (SELECT 1 FROM vending_products WHERE product_id = NEW.product_id)
        THEN RAISE(ABORT, 'vending_product_not_found')
    END;
    SELECT CASE
        WHEN EXISTS (
            SELECT 1 FROM vending_products
            WHERE product_id = NEW.product_id
              AND machine_id IS NOT NULL
              AND machine_id <> NEW.machine_id
        )
        THEN RAISE(ABORT, 'vending_product_machine_mismatch')
    END;
    SELECT CASE
        WHEN NEW.idempotency_key IS NOT NULL
         AND EXISTS (SELECT 1 FROM vending_transactions WHERE idempotency_key = NEW.idempotency_key)
        THEN RAISE(ABORT, 'vending_idempotency_key_conflict')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_vending_transaction_integrity_update
BEFORE UPDATE OF machine_id, product_id, amount, idempotency_key ON vending_transactions
BEGIN
    SELECT CASE
        WHEN NEW.amount IS NULL OR NEW.amount < 0
        THEN RAISE(ABORT, 'vending_transaction_amount_must_be_nonnegative')
    END;
    SELECT CASE
        WHEN NOT EXISTS (SELECT 1 FROM vending_machines WHERE machine_id = NEW.machine_id)
        THEN RAISE(ABORT, 'vending_machine_not_found')
    END;
    SELECT CASE
        WHEN NOT EXISTS (SELECT 1 FROM vending_products WHERE product_id = NEW.product_id)
        THEN RAISE(ABORT, 'vending_product_not_found')
    END;
    SELECT CASE
        WHEN EXISTS (
            SELECT 1 FROM vending_products
            WHERE product_id = NEW.product_id
              AND machine_id IS NOT NULL
              AND machine_id <> NEW.machine_id
        )
        THEN RAISE(ABORT, 'vending_product_machine_mismatch')
    END;
    SELECT CASE
        WHEN NEW.idempotency_key IS NOT NULL
         AND EXISTS (
             SELECT 1 FROM vending_transactions
             WHERE idempotency_key = NEW.idempotency_key
               AND transaction_id <> NEW.transaction_id
         )
        THEN RAISE(ABORT, 'vending_idempotency_key_conflict')
    END;
END;
