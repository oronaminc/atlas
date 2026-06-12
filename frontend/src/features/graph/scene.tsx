/** Three.js scene: incident spheres, host boxes, edge lines, sprite labels.
 *  drei is intentionally NOT used (its Text loads fonts remotely — air-gap);
 *  controls come from three/examples, labels from canvas textures. */

import { useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { PositionedNode } from "@/features/graph/layout";
import type { GraphEdge } from "@/types";

const SEVERITY_COLOR: Record<string, string> = {
  critical: "#ef4444",
  warning: "#f59e0b",
  info: "#3b82f6",
};
const HOST_COLOR = "#64748b";
const EDGE_COLOR: Record<string, string> = {
  host: "#475569",
  temporal: "#22d3ee",
  same_name: "#a78bfa",
  member: "#94a3b8",
};

function makeLabelSprite(text: string): THREE.Sprite {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  const font = "24px sans-serif";
  ctx.font = font;
  canvas.width = Math.ceil(ctx.measureText(text).width) + 16;
  canvas.height = 36;
  ctx.font = font;
  ctx.fillStyle = "rgba(15, 23, 42, 0.75)";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#e2e8f0";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 8, canvas.height / 2);
  const texture = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: texture, depthTest: false }),
  );
  sprite.scale.set(canvas.width / 18, canvas.height / 18, 1);
  return sprite;
}

function Controls() {
  const { camera, gl } = useThree();
  const controls = useRef<OrbitControls>();
  useEffect(() => {
    controls.current = new OrbitControls(camera, gl.domElement);
    controls.current.enableDamping = true;
    return () => controls.current?.dispose();
  }, [camera, gl]);
  useFrame(() => controls.current?.update());
  return null;
}

function NodeMesh({
  node,
  selected,
  onSelect,
}: {
  node: PositionedNode;
  selected: boolean;
  onSelect: (node: PositionedNode) => void;
}) {
  const isHost = node.kind === "host";
  const isAlert = node.kind === "alert";
  const color = isHost
    ? HOST_COLOR
    : SEVERITY_COLOR[node.severity ?? "info"] ?? SEVERITY_COLOR.info;
  const radius = isHost
    ? 3.5
    : isAlert
      ? 1.2
      : 1.8 + Math.min(Math.log2(1 + (node.alert_count ?? 1)), 3);
  const opacity = node.status === "resolved" ? 0.35 : 1;

  const handleClick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect(node);
  };

  return (
    <group position={[node.x, node.y, node.z]}>
      <mesh onClick={handleClick}>
        {isHost ? (
          <boxGeometry args={[radius, radius, radius]} />
        ) : (
          <sphereGeometry args={[radius, 16, 16]} />
        )}
        <meshStandardMaterial
          color={color}
          transparent
          opacity={opacity}
          emissive={selected ? color : "#000000"}
          emissiveIntensity={selected ? 0.7 : 0}
        />
      </mesh>
      {isHost && <HostLabel text={node.label} offsetY={radius + 2} />}
    </group>
  );
}

function HostLabel({ text, offsetY }: { text: string; offsetY: number }) {
  const sprite = useMemo(() => makeLabelSprite(text), [text]);
  useEffect(() => () => sprite.material.map?.dispose(), [sprite]);
  return <primitive object={sprite} position={[0, offsetY, 0]} />;
}

function Edges({
  edges,
  positions,
}: {
  edges: GraphEdge[];
  positions: Map<string, PositionedNode>;
}) {
  const groups = useMemo(() => {
    const byKind = new Map<string, number[]>();
    for (const edge of edges) {
      const a = positions.get(edge.source);
      const b = positions.get(edge.target);
      if (!a || !b) continue;
      const list = byKind.get(edge.kind) ?? [];
      list.push(a.x, a.y, a.z, b.x, b.y, b.z);
      byKind.set(edge.kind, list);
    }
    return [...byKind.entries()];
  }, [edges, positions]);

  return (
    <>
      {groups.map(([kind, coords]) => {
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute(
          "position",
          new THREE.Float32BufferAttribute(coords, 3),
        );
        return (
          <lineSegments key={kind} geometry={geometry}>
            <lineBasicMaterial
              color={EDGE_COLOR[kind] ?? "#475569"}
              transparent
              opacity={kind === "host" ? 0.25 : 0.6}
            />
          </lineSegments>
        );
      })}
    </>
  );
}

export function GraphScene({
  nodes,
  edges,
  selectedId,
  onSelect,
}: {
  nodes: PositionedNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  onSelect: (node: PositionedNode | null) => void;
}) {
  const positions = useMemo(
    () => new Map(nodes.map((n) => [n.id, n])),
    [nodes],
  );

  return (
    <Canvas
      camera={{ position: [0, 40, 160], fov: 55 }}
      // preserveDrawingBuffer so screenshots/e2e capture the WebGL canvas
      gl={{ preserveDrawingBuffer: true, antialias: true }}
      onPointerMissed={() => onSelect(null)}
    >
      <color attach="background" args={["#0b1220"]} />
      <ambientLight intensity={0.7} />
      <directionalLight position={[50, 80, 60]} intensity={1.1} />
      <Controls />
      {nodes.map((node) => (
        <NodeMesh
          key={node.id}
          node={node}
          selected={node.id === selectedId}
          onSelect={(n) => onSelect(n)}
        />
      ))}
      <Edges edges={edges} positions={positions} />
      <gridHelper args={[300, 30, "#1e293b", "#16202f"]} position={[0, -70, 0]} />
    </Canvas>
  );
}
