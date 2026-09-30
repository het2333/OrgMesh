import { notFound } from "next/navigation";
import PresentationEditor from "@/sections/workspace/presentations/PresentationEditor";
import { isPresentationId } from "@/sections/workspace/presentations/types";

interface PresentationPageProps {
  params: Promise<{ id: string }>;
}

export default async function PresentationPage({
  params,
}: PresentationPageProps) {
  const { id } = await params;
  if (!isPresentationId(id)) notFound();
  return <PresentationEditor key={id} id={id} />;
}
