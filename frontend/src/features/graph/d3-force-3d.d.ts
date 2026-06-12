declare module "d3-force-3d" {
  export interface SimNode {
    id: string;
    x?: number;
    y?: number;
    z?: number;
    fx?: number | null;
    fy?: number | null;
    fz?: number | null;
    [key: string]: unknown;
  }
  export interface SimLink {
    source: string | SimNode;
    target: string | SimNode;
    [key: string]: unknown;
  }
  export interface Simulation {
    nodes(nodes: SimNode[]): Simulation;
    force(name: string, force: unknown | null): Simulation;
    stop(): Simulation;
    tick(n?: number): Simulation;
    alpha(a: number): Simulation;
  }
  export function forceSimulation(nodes?: SimNode[], numDimensions?: number): Simulation;
  export interface LinkForce {
    id(fn: (n: SimNode) => string): LinkForce;
    distance(d: number | ((l: SimLink) => number)): LinkForce;
    strength(s: number | ((l: SimLink) => number)): LinkForce;
  }
  export function forceLink(links?: SimLink[]): LinkForce;
  export function forceManyBody(): { strength(s: number): unknown };
  export function forceCollide(r?: number | ((n: SimNode) => number)): unknown;
  export function forceX(x?: number | ((n: SimNode) => number)): { strength(s: number): unknown };
  export function forceY(y?: number | ((n: SimNode) => number)): { strength(s: number): unknown };
  export function forceZ(z?: number | ((n: SimNode) => number)): { strength(s: number): unknown };
  export function forceCenter(x?: number, y?: number, z?: number): unknown;
}
