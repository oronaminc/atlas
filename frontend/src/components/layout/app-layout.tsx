import { Suspense, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Activity,
  BellOff,
  BellRing,
  ClipboardList,
  Gauge,
  LayoutDashboard,
  Layers,
  LogOut,
  Menu,
  Network,
  Server,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  User as UserIcon,
  Users,
  UsersRound,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { ThemeToggle } from "@/components/common/theme-toggle";
import { GlobalSearch } from "@/components/layout/global-search";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  labelKey: string;
  icon: React.ComponentType<{ className?: string }>;
  adminOnly?: boolean;
}

interface NavSection {
  labelKey: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    labelKey: "nav.sectionMonitor",
    items: [
      { to: "/", labelKey: "nav.dashboard", icon: LayoutDashboard },
      { to: "/ops", labelKey: "nav.ops", icon: Gauge },
      { to: "/graph", labelKey: "nav.graph", icon: Network },
      { to: "/alerts", labelKey: "nav.alerts", icon: Activity },
    ],
  },
  {
    labelKey: "nav.sectionConfigure",
    items: [
      { to: "/servers", labelKey: "nav.servers", icon: Server },
      { to: "/rules", labelKey: "nav.rules", icon: ShieldAlert },
      { to: "/rule-groups", labelKey: "nav.ruleGroups", icon: Layers },
      { to: "/notifications", labelKey: "nav.notifications", icon: BellRing },
      { to: "/mutes", labelKey: "nav.mutes", icon: BellOff },
      { to: "/thresholds", labelKey: "nav.thresholds", icon: SlidersHorizontal },
    ],
  },
  {
    labelKey: "nav.sectionAdmin",
    items: [
      { to: "/groups", labelKey: "nav.groups", icon: UsersRound },
      { to: "/users", labelKey: "nav.users", icon: Users, adminOnly: true },
      { to: "/settings", labelKey: "nav.settings", icon: Settings, adminOnly: true },
      { to: "/audit", labelKey: "nav.audit", icon: ClipboardList },
    ],
  },
];

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  const { hasRole } = useAuth();

  return (
    <nav className="flex flex-col gap-5 px-3">
      {navSections.map((section) => {
        const items = section.items.filter(
          (item) => !item.adminOnly || hasRole("admin"),
        );
        if (items.length === 0) return null;
        return (
          <div key={section.labelKey} className="flex flex-col gap-1">
            <p className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">
              {t(section.labelKey)}
            </p>
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                onClick={onNavigate}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                  )
                }
              >
                <item.icon className="h-4 w-4" />
                {t(item.labelKey)}
              </NavLink>
            ))}
          </div>
        );
      })}
    </nav>
  );
}

function Brand() {
  return (
    <div className="flex h-14 items-center gap-2 border-b border-border/60 px-4">
      <Activity className="h-5 w-5 text-primary" />
      <span className="text-lg font-semibold tracking-tight">Atlas</span>
    </div>
  );
}

export function AppLayout() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="grid h-screen grid-cols-1 md:grid-cols-[240px_1fr]">
      {/* Desktop sidebar */}
      <aside className="hidden flex-col border-r border-border/60 bg-card md:flex">
        <Brand />
        <div className="flex-1 overflow-y-auto py-4">
          <SidebarNav />
        </div>
      </aside>

      <div className="flex h-screen flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border/60 px-4">
          {/* Mobile menu */}
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden">
                <Menu className="h-5 w-5" />
                <span className="sr-only">Menu</span>
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64 p-0">
              <Brand />
              <div className="py-4">
                <SidebarNav onNavigate={() => setMobileOpen(false)} />
              </div>
            </SheetContent>
          </Sheet>

          <div className="mx-2 hidden flex-1 sm:block">
            <GlobalSearch />
          </div>
          <div className="flex-1 sm:hidden" />

          <ThemeToggle />

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="gap-2 px-2">
                <Avatar className="h-8 w-8">
                  <AvatarFallback>
                    {user?.username?.slice(0, 2).toUpperCase() ?? "?"}
                  </AvatarFallback>
                </Avatar>
                <span className="hidden text-sm font-medium sm:inline">
                  {user?.username}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuLabel className="truncate">
                {user?.email}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate("/profile")}>
                <UserIcon className="h-4 w-4" />
                {t("nav.profile")}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate("/profile")}>
                <Settings className="h-4 w-4" />
                {t("auth.changePassword")}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout}>
                <LogOut className="h-4 w-4" />
                {t("nav.logout")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        {/* Content. Suspense catches every lazily-loaded route chunk. */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          <Suspense fallback={<LoadingSpinner />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
