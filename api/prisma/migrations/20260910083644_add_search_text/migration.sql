-- AlterTable
ALTER TABLE "messages" ADD COLUMN     "search_text" TEXT NOT NULL DEFAULT '';

-- Backfill existing rows: approximate the ingest's searchable_text with the
-- content plus the embed JSON as text. New rows get the precise value from the
-- ingest service; both are adequate for case-insensitive substring search.
UPDATE "messages" SET "search_text" = "content" || ' ' || "embeds"::text
WHERE "search_text" = '';
