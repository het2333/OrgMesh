import { notFound } from "next/navigation";
import DocumentEditor from "@/sections/workspace/documents/DocumentEditor";
import { isDocumentId } from "@/sections/workspace/documents/api";

export default async function DocumentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!isDocumentId(id)) notFound();
  return <DocumentEditor key={id} id={id} />;
}
