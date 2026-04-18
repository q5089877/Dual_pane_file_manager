import os

svg_icons = {
    # 1. pin
    "pin": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 2L14 6L11 9L12 14L8 11L4 15L2 13L6 9L1 8L4 5L8 9L10 2Z" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
</svg>""",
    # 2. camera
    "camera": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M4 4C4 3.45 4.45 3 5 3H11C11.55 3 12 3.45 12 4V5H14C14.55 5 15 5.45 15 6V13C15 13.55 14.55 14 14 14H2C1.45 14 1 13.55 1 13V6C1 5.45 1.45 5 2 5H4V4Z" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
  <circle cx="8" cy="9.5" r="2.5" stroke="{color}" stroke-width="{stroke}" fill="none"/>
</svg>""",
    # 3. package (basket)
    "package": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 2L14 5V11L8 14L2 11V5L8 2Z" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
  <path d="M2 5L8 8L14 5" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
  <path d="M8 8V14" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
</svg>""",
    # 4. trash
    "trash": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M3 4H13" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round"/>
  <path d="M5 4V2C5 1.45 5.45 1 6 1H10C10.55 1 11 1.45 11 2V4" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
  <path d="M4 4L5 14C5 14.55 5.45 15 6 15H10C10.55 15 11 14.55 11 14L12 4" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
  <path d="M7 7V12" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round"/>
  <path d="M9 7V12" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round"/>
</svg>""",
    # 5. copy
    "copy": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 4V3C5 2.45 5.45 2 6 2H12C12.55 2 13 2.45 13 3V10C13 10.55 12.55 11 12 11H11" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
  <rect x="3" y="6" width="6" height="8" rx="1" stroke="{color}" stroke-width="{stroke}" fill="none"/>
</svg>""",
    # 6. compare (arrows)
    "compare": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M5 4L2 7M2 7L5 10M2 7H14" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
  <path d="M11 12L14 9M14 9L11 6M14 9H2" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
</svg>""",
    # 7. extract (box arrow up)
    "extract": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M3 6V13C3 13.55 3.45 14 4 14H12C12.55 14 13 13.55 13 13V6" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
  <path d="M10 5L8 3L6 5" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
  <path d="M8 3V10" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" fill="none"/>
</svg>""",
    # 8. folder
    "folder": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M2 13V4C2 3.45 2.45 3 3 3H6L8 5H13C13.55 5 14 5.45 14 6V13C14 13.55 13.55 14 13 14H3C2.45 14 2 13.55 2 13Z" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
</svg>""",
    # 9. file
    "file": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M4 2V14C4 14.55 4.45 15 5 15H11C11.55 15 12 14.55 12 14V6L8 2H5C4.45 2 4 2.45 4 4Z" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
  <path d="M8 2V6H12" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
</svg>""",
     # 10. save
    "save": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M3 2V14C3 14.55 3.45 15 4 15H12C12.55 15 13 14.55 13 14V5L10 2H4C3.45 2 3 2.45 3 3Z" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
  <path d="M10 2V6H6" stroke="{color}" stroke-width="{stroke}" stroke-linejoin="round" fill="none"/>
  <rect x="5" y="10" width="6" height="5" stroke="{color}" stroke-width="{stroke}" fill="none"/>
</svg>""",
    # 11. x (close)
    "close": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M4 4L12 12M4 12L12 4" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" fill="none"/>
</svg>""",
    # 12. check (checkmark)
    "check": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <path d="M3.5 8L6.5 11L12.5 5" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
</svg>"""
}

# The existing list_view / grid_view active variations
active_svgs = {
    "list_view_active": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <line x1="4" y1="5" x2="13" y2="5" stroke="#FFFFFF" stroke-width="1.2" stroke-linecap="round"/>
  <line x1="4" y1="8" x2="13" y2="8" stroke="#FFFFFF" stroke-width="1.2" stroke-linecap="round"/>
  <line x1="4" y1="11" x2="13" y2="11" stroke="#FFFFFF" stroke-width="1.2" stroke-linecap="round"/>
</svg>""",
    "grid_view_active": """<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <rect x="2" y="2" width="5" height="5" rx="1" stroke="#FFFFFF" stroke-width="1.2" fill="none"/>
  <rect x="9" y="2" width="5" height="5" rx="1" stroke="#FFFFFF" stroke-width="1.2" fill="none"/>
  <rect x="2" y="9" width="5" height="5" rx="1" stroke="#FFFFFF" stroke-width="1.2" fill="none"/>
  <rect x="9" y="9" width="5" height="5" rx="1" stroke="#FFFFFF" stroke-width="1.2" fill="none"/>
</svg>"""
}


def create():
    # Use a relative path based on the script location to ensure it works in any directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(base_dir, "ui")
    os.makedirs(out_dir, exist_ok=True)
    
    for name, tpl in svg_icons.items():
        # Standard gray version
        filepath = os.path.join(out_dir, f"{name}.svg")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(tpl.format(color="#C9D1D9", stroke="1"))
            
        # Active white version
        active_filepath = os.path.join(out_dir, f"{name}_active.svg")
        with open(active_filepath, "w", encoding="utf-8") as f:
            f.write(tpl.format(color="#FFFFFF", stroke="1"))
            
    for name, content in active_svgs.items():
        filepath = os.path.join(out_dir, f"{name}.svg")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

if __name__ == "__main__":
    create()
