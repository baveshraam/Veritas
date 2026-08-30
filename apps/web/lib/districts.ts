/** Karnataka's 31 real districts, code -> name. Static reference data, so it is
 *  duplicated rather than fetched — the same convention viz/MapView.tsx's own
 *  DISTRICTS array already follows, which additionally carries centroids this
 *  lookup does not need. */
export const DISTRICT_NAMES: Record<string, string> = {
  KA01: "Bagalkot", KA02: "Ballari", KA03: "Belagavi", KA04: "Bengaluru Rural",
  KA05: "Bengaluru Urban", KA06: "Bidar", KA07: "Vijayapura", KA08: "Chamarajanagar",
  KA09: "Chikkaballapura", KA10: "Chikkamagaluru", KA11: "Chitradurga",
  KA12: "Dakshina Kannada", KA13: "Davanagere", KA14: "Dharwad", KA15: "Gadag",
  KA16: "Kalaburagi", KA17: "Hassan", KA18: "Haveri", KA19: "Kodagu", KA20: "Kolar",
  KA21: "Koppal", KA22: "Mandya", KA23: "Mysuru", KA24: "Raichur", KA25: "Ramanagara",
  KA26: "Shivamogga", KA27: "Tumakuru", KA28: "Udupi", KA29: "Uttara Kannada",
  KA30: "Yadgir", KA31: "Vijayanagara",
};

export const districtName = (code: string): string => DISTRICT_NAMES[code] ?? code;
