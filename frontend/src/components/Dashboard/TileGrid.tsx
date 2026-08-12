import { DASHBOARD_TILES } from "./tileRegistry";

// AC-H2: multiple tiles side-by-side on wider screens, single column on
// narrow (mobile) screens.
export function TileGrid() {
  return (
    <div className="flex flex-wrap gap-3 p-3 sm:gap-4 sm:p-4 justify-center sm:justify-start">
      {DASHBOARD_TILES.map((tile) => (
        <div key={tile.id} className="w-full sm:w-auto">
          {tile.element}
        </div>
      ))}
    </div>
  );
}
