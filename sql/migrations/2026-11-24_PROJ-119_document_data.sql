-- PROJ-119: Structured document data (alice-document-database, stage `database`). Idempotent.
BEGIN;

-- ============================================================
-- 18. STRUCTURED DOCUMENT DATA (PROJ-119)
-- ============================================================
-- Derived from the frontmatter of classified source markdowns (kind `document`)
-- by alice-document-database (stage `database`). Rebuildable at any time from the
-- source of truth; never edited directly. One row per document, one detail row per
-- type, bookings and invoice line items as rows of their own. Amounts and
-- quantities as exact NUMERIC, dates as DATE, NULL stays NULL.

-- 18.1 Stage `database` also runs again when the locations change and when a
-- source is deleted or comes back (removes / re-enters its rows).
UPDATE alice.pipeline_stages SET resets_on_fields = '{locations,deleted}'
 WHERE name = 'database' AND resets_on_fields = '{}';

-- 18.2 One row per document (all types)
CREATE TABLE IF NOT EXISTS alice.doc_documents (
    id                          VARCHAR(12)  PRIMARY KEY,          -- source id (register)
    type                        VARCHAR(20)  NOT NULL
                                CHECK (type IN ('Invoice', 'BankStatement', 'SecuritySettlement', 'Contract', 'Document')),
    title                       TEXT,
    summary                     TEXT,
    tags                        TEXT[],
    document_date               DATE,
    sender                      TEXT,
    recipient                   TEXT,
    language                    TEXT,
    classification_confidence   NUMERIC,
    classification_uncertain    BOOLEAN,
    summary_language_uncertain  BOOLEAN,
    modified                    TIMESTAMPTZ,
    captured                    TIMESTAMPTZ,
    markdown_path               TEXT         NOT NULL,             -- path of the source markdown in the repo
    locations                   JSONB        NOT NULL DEFAULT '[]', -- locations of the originals as in the frontmatter
    synced_at                   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_documents_type ON alice.doc_documents(type);
CREATE INDEX IF NOT EXISTS idx_doc_documents_date ON alice.doc_documents(document_date);
CREATE INDEX IF NOT EXISTS idx_doc_documents_sender ON alice.doc_documents(sender);
CREATE INDEX IF NOT EXISTS idx_doc_documents_tags ON alice.doc_documents USING GIN (tags);

-- 18.3 Detail rows per type
CREATE TABLE IF NOT EXISTS alice.doc_invoices (
    document_id     VARCHAR(12) PRIMARY KEY REFERENCES alice.doc_documents(id) ON DELETE CASCADE,
    invoice_number  TEXT,
    invoice_date    DATE,
    due_date        DATE,
    amount_gross    NUMERIC,
    amount_net      NUMERIC,
    vat_rate        NUMERIC,
    currency        TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_invoices_date ON alice.doc_invoices(invoice_date);

CREATE TABLE IF NOT EXISTS alice.doc_invoice_line_items (
    document_id  VARCHAR(12) NOT NULL REFERENCES alice.doc_invoices(document_id) ON DELETE CASCADE,
    position     INTEGER     NOT NULL CHECK (position >= 1),
    description  TEXT,
    quantity     NUMERIC,
    amount       NUMERIC,
    PRIMARY KEY (document_id, position)
);

CREATE TABLE IF NOT EXISTS alice.doc_bank_statements (
    document_id         VARCHAR(12) PRIMARY KEY REFERENCES alice.doc_documents(id) ON DELETE CASCADE,
    bank_name           TEXT,
    account_holder      TEXT,
    iban                TEXT,
    period_from         DATE,
    period_to           DATE,
    opening_balance     NUMERIC,
    closing_balance     NUMERIC,
    currency            TEXT,
    balance_mismatch    BOOLEAN,
    balance_difference  NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_doc_bank_statements_iban ON alice.doc_bank_statements(iban);
CREATE INDEX IF NOT EXISTS idx_doc_bank_statements_period ON alice.doc_bank_statements(period_from, period_to);

-- Bookings; duplicate_of points to the booking that counts as the original when the same
-- booking (date, amount, purpose) is in an earlier captured statement of the same IBAN.
CREATE TABLE IF NOT EXISTS alice.doc_bank_transactions (
    id            BIGSERIAL   PRIMARY KEY,
    document_id   VARCHAR(12) NOT NULL REFERENCES alice.doc_bank_statements(document_id) ON DELETE CASCADE,
    position      INTEGER     NOT NULL CHECK (position >= 1),
    booking_date  DATE,
    value_date    DATE,
    counterparty  TEXT,
    purpose       TEXT,
    amount        NUMERIC,
    currency      TEXT,
    duplicate_of  BIGINT      REFERENCES alice.doc_bank_transactions(id) ON DELETE SET NULL,
    UNIQUE (document_id, position)
);

CREATE INDEX IF NOT EXISTS idx_doc_bank_transactions_booking ON alice.doc_bank_transactions(booking_date, amount);
CREATE INDEX IF NOT EXISTS idx_doc_bank_transactions_duplicate ON alice.doc_bank_transactions(duplicate_of)
    WHERE duplicate_of IS NOT NULL;

CREATE TABLE IF NOT EXISTS alice.doc_security_settlements (
    document_id        VARCHAR(12) PRIMARY KEY REFERENCES alice.doc_documents(id) ON DELETE CASCADE,
    bank               TEXT,
    depot_number       TEXT,
    transaction_date   DATE,
    security_name      TEXT,
    isin               TEXT,
    transaction_type   TEXT,
    quantity           NUMERIC,
    price              NUMERIC,
    settlement_amount  NUMERIC,
    currency           TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_security_settlements_isin ON alice.doc_security_settlements(isin);
CREATE INDEX IF NOT EXISTS idx_doc_security_settlements_date ON alice.doc_security_settlements(transaction_date);

CREATE TABLE IF NOT EXISTS alice.doc_contracts (
    document_id       VARCHAR(12) PRIMARY KEY REFERENCES alice.doc_documents(id) ON DELETE CASCADE,
    contract_type     TEXT,
    contract_partner  TEXT,
    sign_date         DATE,
    start_date        DATE,
    end_date          DATE,
    notice_period     TEXT,
    monthly_cost      NUMERIC,
    annual_cost       NUMERIC,
    currency          TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_contracts_partner ON alice.doc_contracts(contract_partner);

-- 18.4 RLS: only the service database user writes these tables; role checks happen in the
-- read tools (PROJ-128)
ALTER TABLE alice.doc_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_invoice_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_bank_statements ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_bank_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_security_settlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE alice.doc_contracts ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['doc_documents', 'doc_invoices', 'doc_invoice_line_items', 'doc_bank_statements',
                             'doc_bank_transactions', 'doc_security_settlements', 'doc_contracts'] LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I_select ON alice.%I', t, t);
        EXECUTE format('DROP POLICY IF EXISTS %I_insert ON alice.%I', t, t);
        EXECUTE format('DROP POLICY IF EXISTS %I_update ON alice.%I', t, t);
        EXECUTE format('DROP POLICY IF EXISTS %I_delete ON alice.%I', t, t);
        EXECUTE format('CREATE POLICY %I_select ON alice.%I FOR SELECT USING (TRUE)', t, t);
        EXECUTE format('CREATE POLICY %I_insert ON alice.%I FOR INSERT WITH CHECK (TRUE)', t, t);
        EXECUTE format('CREATE POLICY %I_update ON alice.%I FOR UPDATE USING (TRUE)', t, t);
        EXECUTE format('CREATE POLICY %I_delete ON alice.%I FOR DELETE USING (TRUE)', t, t);
    END LOOP;
END $$;

COMMIT;
