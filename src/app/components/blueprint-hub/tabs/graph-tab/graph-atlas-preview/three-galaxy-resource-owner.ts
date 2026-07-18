import * as THREE from 'three';

type DisposableGalaxyObject = THREE.Object3D & {
    geometry?: THREE.BufferGeometry;
    material?: THREE.Material | THREE.Material[];
};

export function disposeGalaxyObject(
    scene: THREE.Scene,
    object: THREE.Object3D | null | undefined,
): void {
    if (!object) return;
    scene.remove(object);
    object.traverse((child) => disposeGalaxyDrawable(child as DisposableGalaxyObject));
}

function disposeGalaxyDrawable(drawable: DisposableGalaxyObject): void {
    drawable.geometry?.dispose();
    const material = drawable.material;
    if (Array.isArray(material)) {
        for (const item of material) item.dispose();
    } else {
        material?.dispose();
    }
}
