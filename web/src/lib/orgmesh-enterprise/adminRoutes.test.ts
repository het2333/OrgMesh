import { matchAdminRoute } from "@/lib/admin-routes";
import { buildItems, type FeatureFlags } from "@/lib/admin-sidebar-utils";
import { Permission } from "@/lib/types";
import { Tier } from "@/lib/settings/types";

const flags: FeatureFlags = {
  vectorDbEnabled: false,
  enableCloud: false,
  tier: Tier.COMMUNITY,
  customAnalyticsEnabled: false,
  hasSubscription: false,
  hooksEnabled: false,
  opensearchEnabled: false,
  queryHistoryEnabled: false,
  craftAvailable: false,
};

test.each([
  "/admin/orgmesh-enterprise/branding",
  "/admin/orgmesh-enterprise/audit",
])("independent admin route %s requires full administrator access", (path) => {
  expect(matchAdminRoute(path)?.requiredPermission).toBe(
    Permission.FULL_ADMIN_PANEL_ACCESS
  );
  expect(buildItems([Permission.FULL_ADMIN_PANEL_ACCESS], flags, null)).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ link: path, disabled: false }),
    ])
  );
  expect(
    buildItems([Permission.MANAGE_USER_GROUPS], flags, null).some(
      (item) => item.link === path
    )
  ).toBe(false);
});
