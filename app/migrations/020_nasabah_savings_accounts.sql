-- Ensure every existing Nasabah has an active savings account for finance and payments.
-- Idempotent: repeated migration runs do not create duplicate active savings accounts.
INSERT INTO financial_accounts(account_id,member_id,account_type,status)
SELECT 'acct-auto-' || lower(hex(randomblob(16))), m.member_id, 'savings', 'active'
FROM identity_members AS m
WHERE NOT EXISTS (
    SELECT 1 FROM financial_accounts AS a
    WHERE a.member_id=m.member_id
      AND a.account_type='savings'
      AND a.status='active'
);
