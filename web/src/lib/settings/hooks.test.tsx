/**
 * @jest-environment jsdom
 */
import { renderHook } from "@testing-library/react";
import useSWR from "swr";
import { usePathname } from "next/navigation";
import { FetchError } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";

jest.mock("swr", () => ({
  __esModule: true,
  default: jest.fn(),
}));

jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  usePathname: jest.fn(),
}));

const mockUseSWR = useSWR as jest.MockedFunction<typeof useSWR>;
const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;

function swrResult(overrides: { error?: Error } = {}) {
  return {
    data: undefined,
    error: undefined,
    mutate: jest.fn(),
    isValidating: false,
    isLoading: false,
    ...overrides,
  } as unknown as ReturnType<typeof useSWR>;
}

function stubEnterpriseFetchError(error: Error) {
  mockUseSWR.mockImplementation((key) =>
    key === SWR_KEYS.enterpriseSettings ? swrResult({ error }) : swrResult()
  );
}

// The public brand path never probes legacy enterprise settings.
describe("useSettings independent branding", () => {
  beforeEach(() => {
    mockUseSWR.mockReset();
    mockUsePathname.mockReset();
    mockUsePathname.mockReturnValue("/auth/login");
  });

  test("default branding uses the reviewed local asset without legacy probes", () => {
    const missing = new FetchError("Not Found", 404, {});
    stubEnterpriseFetchError(missing);
    const { result } = renderHook(() => useSettings());
    expect(result.current.error).toBeUndefined();
    expect(result.current.enterprise).toBeNull();
    expect(result.current.appName).toBe("OrgMesh");
    expect(result.current.logoUrl).toBe("/orgmesh.svg");
    expect(
      mockUseSWR.mock.calls.some(([key]) => key === SWR_KEYS.enterpriseSettings)
    ).toBe(false);
  });

  test("a 404 off the auth path is not surfaced either", () => {
    mockUsePathname.mockReturnValue("/app");
    stubEnterpriseFetchError(new FetchError("Not Found", 404, {}));
    const { result } = renderHook(() => useSettings());
    expect(result.current.error).toBeUndefined();
    expect(result.current.enterprise).toBeNull();
  });

  test("legacy failures do not become fatal core settings errors", () => {
    const outage = new FetchError("Internal Server Error", 500, {});
    stubEnterpriseFetchError(outage);
    const { result } = renderHook(() => useSettings());
    expect(result.current.error).toBeUndefined();
    expect(
      mockUseSWR.mock.calls.some(([key]) => key === SWR_KEYS.enterpriseSettings)
    ).toBe(false);
  });
  test("core settings outages still surface", () => {
    mockUsePathname.mockReturnValue("/app");
    const outage = new FetchError("Unavailable", 503, {});
    mockUseSWR.mockImplementation((key) =>
      key === SWR_KEYS.settings ? swrResult({ error: outage }) : swrResult()
    );
    const { result } = renderHook(() => useSettings());
    expect(result.current.error).toBe(outage);
    expect(result.current.appName).toBe("OrgMesh");
  });
});
