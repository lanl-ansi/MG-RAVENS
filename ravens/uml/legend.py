from textwrap import wrap
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon

# Define the colors used in the RAVENS uml
ravens_colors =  {'#dda0dd' : 'magenta',
             "#98fb98": "green",
             "#fffacd": "yellow",
             "#87ceeb": "blue",
             "#e8fde3": "lightgreen",
             "#ffffff": "white",
             "#ffc0cb": 'pink',
             "#800000" : 'red connector',
             "#2e8b57": 'green connector',
             "#000000": 'black connector'}


def make_ravens_legend():
    objects = {
        "#dda0dd": 'Properties inherited from generalization "above" this class are absorbed into this class, '
        'and generalizations "below" this class are turned into anyOf in the schema at the level of this object',
        "#98fb98": "association that only lives within a purple object, does not exist at the root level",
        "#fffacd": "default object; has objects nested beneath it",
        "#87ceeb": "compound (datatype that is a level above primitive), object has multiple attributes of subproperties",
        "#e8fde3": "enumerations (datatype, always a string)",
        "#ffffff": "root level object; should only appear in Root diagram",
    }

    connectors = {
        "#800000": " association; implies no inheritance (inherits the object it points at). The object being referenced exists elsewhere in schema. "
        "In JSON, this also indicates the property (objecttype:reference) is a string.",
        "#2e8b57": "composedof? property is directly within an object; does not exist elsewhere.",
        # there maybe should be an open diamond symbol too
    }

    black_connectors = {
        "▷": "generalization; object B is a generalization of the object it points at. implies inheritance. Color is irrelevant.",
        "◇": "composition; primarily (exclusively?) for root connections",
    }

    fig, ax = plt.subplots(figsize=(8.5, 6.5))  # Slightly wider for padding
    ax.axis("off")

    # Layout settings
    box_width = 1.25
    box_height = 0.5
    spacing = 0.15
    label_spacing = 0.25
    section_gap = 0.4
    title_gap = 0.1

    # Wrapping settings
    wrap_width = 100
    label_x = 0.5 + box_width + 0.2

    y = 0
    min_y = 0

    # --- Objects section ---
    ax.text(
        0.5 + box_width / 2,
        y,
        "Objects",
        ha="center",
        va="bottom",
        fontsize=12,
        fontweight="bold",
    )
    y -= title_gap

    for color, label in objects.items():
        y -= box_height + spacing
        ax.add_patch(
            Rectangle((0.5, y), box_width, box_height, color=color, ec="black")
        )
        wrapped_label = "\n".join(wrap(label, width=wrap_width))
        ax.text(label_x, y + box_height / 2, wrapped_label, va="center", fontsize=9)
        min_y = min(min_y, y - 0.25 * wrapped_label.count("\n"))  # adjust for multiline

    # --- Connectors section ---
    y -= section_gap
    ax.text(
        0.5 + box_width / 2,
        y,
        "Connectors",
        ha="center",
        va="bottom",
        fontsize=12,
        fontweight="bold",
    )
    y -= title_gap

    for color, label in connectors.items():
        y -= label_spacing
        ax.plot([0.5, 0.5 + box_width], [y, y], color=color, linewidth=3)
        wrapped_label = "\n".join(wrap(label, width=wrap_width))
        ax.text(label_x, y, wrapped_label, va="center", fontsize=9)
        min_y = min(min_y, y - 0.25 * wrapped_label.count("\n"))

    # Black connectors with symbols
    symbol_offset = 0.15
    bolinewidth = 1.5

    for symbol, label in black_connectors.items():
        y -= label_spacing
        line_start = 0.5
        line_end = 0.5 + box_width - symbol_offset

        ax.plot([line_start, line_end], [y, y], color="black", linewidth=bolinewidth)

        if symbol == "▷":
            triangle = Polygon(
                [
                    (line_end + symbol_offset, y),
                    (line_end, y + 0.05),
                    (line_end, y - 0.05),
                ],
                closed=True,
                facecolor="white",
                edgecolor="black",
                linewidth=bolinewidth,
            )
            ax.add_patch(triangle)

        elif symbol == "◇":
            diamond = Polygon(
                [
                    (line_end + 0.14, y),
                    (line_end + 0.07, y + 0.05),
                    (line_end, y),
                    (line_end + 0.07, y - 0.05),
                ],
                closed=True,
                facecolor="white",
                edgecolor="black",
                linewidth=bolinewidth,
            )
            ax.add_patch(diamond)

        wrapped_label = "\n".join(wrap(label, width=wrap_width))
        ax.text(label_x, y, wrapped_label, va="center", fontsize=9)
        min_y = min(min_y, y - 0.25 * wrapped_label.count("\n"))

    # Final layout
    ax.set_xlim(0, 5.5)
    ax.set_ylim(min_y - 0.5, 1)

    plt.tight_layout()
    plt.show()
