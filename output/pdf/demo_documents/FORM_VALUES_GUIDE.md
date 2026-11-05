# Synthetic PS2 demo guide

All PDFs in this folder are fictional software-test samples. They are not government registrations, bank records, or evidence for a real organization.

## 1. Matching happy path - Approved

Use these values with `happy_path_gst.pdf` and `happy_path_bank.pdf`:

| Form field | Synthetic value |
|---|---|
| Legal company name | Acme Demo Technologies Private Limited |
| Contact name | Meghana Sai |
| Contact email | meghana@example.test |
| Country | India |
| GSTIN | 27AAPFU0939F1ZV |
| Bank beneficiary name | Acme Demo Technologies Private Limited |
| Bank account number | 001234567890 |
| IFSC | HDFC0001234 |

Expected result: `Approved`. All supported form-to-document comparisons match.

## 2. Legitimate legal-name exception - Pending

Use these values with `sole_proprietor_name_gst.pdf` and `sole_proprietor_name_bank.pdf`:

| Form field | Synthetic value |
|---|---|
| Legal company name | Meghana Sai Designs |
| Contact name | Meghana Sai |
| Contact email | meghana@example.test |
| Country | India |
| GSTIN | 27AAPFU0939F1ZV |
| Bank beneficiary name | Meghana Sai Designs |
| Bank account number | 001234567890 |
| IFSC | HDFC0001234 |

Expected result: `Pending` with `NAME_REVIEW_REQUIRED`. The trade name differs from the proprietor name shown in both documents. The app must request human review rather than fuzzy-matching or rejecting automatically.

## 3. Mixed-identity evidence - Pending

Use the happy-path form values from scenario 1 with `mixed_identity_gst.pdf` and `mixed_identity_bank.pdf`.

Expected result: `Pending`. The bank proof belongs to the submitted vendor, but the GST evidence contains a different legal company name and a different checksum-valid GSTIN. This simulates a wrong-document or identity-mix-up risk.

## 4. Changed bank details after approval - Pending

This is a two-run history scenario in the same browser session:

1. Run scenario 1 first and confirm it is `Approved`.
2. Then use `bank_change_gst.pdf` and `bank_change_bank.pdf` with the values below.

| Form field | Synthetic value |
|---|---|
| Legal company name | Acme Demo Technologies Private Limited |
| Contact name | Meghana Sai |
| Contact email | meghana@example.test |
| Country | India |
| GSTIN | 27AAPFU0939F1ZV |
| Bank beneficiary name | Acme Demo Technologies Private Limited |
| Bank account number | 009999888877 |
| IFSC | ICIC0005678 |

Expected result: `Pending` with `BANK_DETAILS_CHANGED`. All five current form-to-document comparisons match, but the application detects that the verified bank details changed since the previous Approved run for the same GSTIN.

## 5. Shared bank account across vendor identities - Pending

This is another two-run history scenario:

1. Run scenario 1 first and confirm it is `Approved`.
2. Then use `shared_account_gst.pdf` and `shared_account_bank.pdf` with the values below.

| Form field | Synthetic value |
|---|---|
| Legal company name | Bluebird Demo Services Private Limited |
| Contact name | Meghana Sai |
| Contact email | meghana@example.test |
| Country | India |
| GSTIN | 07ABCDE1234F1Z2 |
| Bank beneficiary name | Bluebird Demo Services Private Limited |
| Bank account number | 001234567890 |
| IFSC | HDFC0001234 |

Expected result: `Pending` with `BANK_ACCOUNT_REUSED`. Every current form-to-document comparison matches, but the same verified account was previously Approved for Acme under a different GSTIN.

## 6. Explicit internal blocklist - Rejected

Use these values with `blocked_vendor_gst.pdf` and `blocked_vendor_bank.pdf`:

| Form field | Synthetic value |
|---|---|
| Legal company name | Northstar Demo Supplies Private Limited |
| Contact name | Meghana Sai |
| Contact email | meghana@example.test |
| Country | India |
| GSTIN | 29AAPFU0939F1ZR |
| Bank beneficiary name | Northstar Demo Supplies Private Limited |
| Bank account number | 007700660055 |
| IFSC | SBIN0002468 |

Expected result: `Rejected` with `POLICY_BLOCKED_VENDOR`. The document-supported GSTIN exactly matches the synthetic prohibited-vendor policy in `data/blocked_vendors.json`. This is the only rejection rule in the demo.

## Recommended live-demo order

For a concise demonstration:

1. Happy path - show the evidence provenance and Approved result.
2. Changed bank details - show that all current fields match but history still triggers Pending.
3. Blocklisted vendor - show the explicit, evidence-supported Rejected path.

Use the shared-account scenario as an additional interview edge case if asked. The dashboard should show concise primary reasons, masked accounts, and detailed evidence/findings for the selected run.
