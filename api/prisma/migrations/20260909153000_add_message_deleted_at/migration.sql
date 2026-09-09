-- AlterTable
ALTER TABLE "messages" ADD COLUMN     "deleted_at" TIMESTAMPTZ(6);

-- CreateIndex
CREATE INDEX "messages_deleted_at_idx" ON "messages"("deleted_at");
