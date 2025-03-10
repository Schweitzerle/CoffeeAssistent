quantities_per_type = {
    "espresso": (35,60),
    "espresso macchiato": (40,60),
    "coffee": (60, 250),
    "cappuccino": (100, 300),
    "latte macchiato": (200, 400),
    "caffe latte": (100, 400)
}

def get_quantity_per_type(type):
    range = quantities_per_type[type.lower()]

    return range[0], range[1]
