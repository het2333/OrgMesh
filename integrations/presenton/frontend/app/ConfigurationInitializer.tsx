"use client";

import { useEffect, useState } from "react";
import { useDispatch } from "react-redux";
import { setCanChangeKeys, setLLMConfig } from "@/store/slices/userConfig";

interface NativePresentationStatus {
  model_name?: string;
  image_generation?: boolean;
}

export function ConfigurationInitializer({ children }: { children: React.ReactNode }) {
  const dispatch = useDispatch();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    dispatch(setCanChangeKeys(false));
    // Native model credentials remain on the OrgMesh server.
    dispatch(setLLMConfig({
      LLM: "custom",
      CUSTOM_MODEL: "OrgMesh",
      DISABLE_IMAGE_GENERATION: true,
    }));

    async function loadNativeModel() {
      try {
        const response = await fetch("/api/orgmesh/presenton/status", {
          cache: "no-store",
          credentials: "same-origin",
        });
        if (!response.ok) return;
        const status: NativePresentationStatus = await response.json();
        if (!cancelled) {
          dispatch(setLLMConfig({
            LLM: "custom",
            CUSTOM_MODEL: status.model_name || "OrgMesh",
            DISABLE_IMAGE_GENERATION: status.image_generation !== true,
          }));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadNativeModel().catch(() => undefined);
    return () => { cancelled = true; };
  }, [dispatch]);

  if (loading) {
    return (
      <div className="flex h-dvh items-center justify-center bg-white font-syne" role="status" aria-busy="true">
        正在加载演示文稿编辑器…
      </div>
    );
  }
  return children;
}
