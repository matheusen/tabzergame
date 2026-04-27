extends SceneTree

const OUT_DIR := "res://art/Player/Generated"
const MOVEMENT_SHEET := "res://art/Player/ChatGPT Image 24 de abr. de 2026, 17_32_38.png"
const ACTION_SHEET := "res://art/Player/ChatGPT Image 24 de abr. de 2026, 17_32_30.png"
const CROUCH_SHEET := "res://art/Player/player_abaixando.png"
const CROUCH_MOVE_SHEET := "res://art/Player/player_abaixado_andando.png"
const ATTACK_SHEET := "res://art/Player/assets_attack.png"
const FRAME_SIZE := Vector2i(320, 260)
const ATTACK_FRAME_SIZE := FRAME_SIZE
const HEAVY_ATTACK_FRAME_SIZE := FRAME_SIZE
const BASELINE_Y := 246

const ANIMS := {
	"idle": {
		"source": MOVEMENT_SHEET,
		"fixed_scale": 0.84,
		"rects": [
			Rect2i(100, 18, 214, 219),
			Rect2i(314, 18, 213, 219),
			Rect2i(527, 18, 211, 219),
		],
	},
	"run": {
		"source": MOVEMENT_SHEET,
		"fixed_scale": 0.84,
		"rects": [
			Rect2i(100, 238, 213, 230),
			Rect2i(314, 238, 213, 230),
			Rect2i(527, 238, 211, 230),
			Rect2i(738, 238, 213, 230),
			Rect2i(951, 238, 211, 230),
			Rect2i(1162, 238, 220, 230),
		],
	},
	"jump": {
		"source": MOVEMENT_SHEET,
		"fixed_scale": 0.84,
		"rects": [
			Rect2i(100, 470, 213, 228),
			Rect2i(314, 470, 213, 228),
			Rect2i(527, 470, 211, 228),
		],
	},
	"crouch_down": {
		"source": CROUCH_SHEET,
		"fixed_scale": 0.46,
		"rects": [
			Rect2i(48, 285, 360, 450),
			Rect2i(410, 305, 360, 430),
			Rect2i(760, 330, 360, 405),
			Rect2i(1100, 350, 330, 385),
		],
	},
	"crouch": {
		"source": CROUCH_SHEET,
		"fixed_scale": 0.46,
		"rects": [
			Rect2i(1100, 350, 330, 385),
		],
	},
	"crouch_move": {
		"source": CROUCH_MOVE_SHEET,
		"fixed_scale": 0.72,
		"rects": [
			Rect2i(64, 338, 220, 176),
			Rect2i(304, 340, 210, 174),
			Rect2i(530, 347, 190, 166),
			Rect2i(765, 344, 210, 170),
			Rect2i(1018, 346, 210, 166),
			Rect2i(1250, 346, 190, 168),
		],
	},
	"attack_light": {
		"source": ATTACK_SHEET,
		"frame_size": ATTACK_FRAME_SIZE,
		"fixed_scale": 0.74,
		"rects": [
			Rect2i(32, 150, 245, 310),
			Rect2i(292, 150, 260, 310),
			Rect2i(560, 150, 325, 310),
			Rect2i(930, 150, 290, 310),
			Rect2i(1218, 150, 230, 310),
		],
	},
	"attack_heavy": {
		"source": ATTACK_SHEET,
		"frame_size": HEAVY_ATTACK_FRAME_SIZE,
		"fixed_scale": 0.74,
		"offset_x": 26,
		"rects": [
			Rect2i(28, 580, 220, 330),
			Rect2i(268, 500, 225, 410),
			Rect2i(505, 545, 230, 365),
			Rect2i(706, 505, 330, 405),
			Rect2i(998, 585, 250, 325),
			Rect2i(1236, 580, 212, 330),
		],
	},
}


func _init() -> void:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(OUT_DIR))

	var cleaned_by_source := {}
	for animation_name in ANIMS:
		var config: Dictionary = ANIMS[animation_name]
		var source_path := String(config["source"])
		if not cleaned_by_source.has(source_path):
			cleaned_by_source[source_path] = _load_clean_sheet(source_path)
			var clean_name := "player_%s_clean.png" % source_path.get_file().get_basename().right(8)
			cleaned_by_source[source_path].save_png("%s/%s" % [OUT_DIR, clean_name])

		var clean_sheet: Image = cleaned_by_source[source_path]
		var fixed_scale := -1.0
		if config.has("fixed_scale"):
			fixed_scale = float(config["fixed_scale"])
		var frame_size := FRAME_SIZE
		if config.has("frame_size"):
			frame_size = config["frame_size"] as Vector2i
		var baseline_y := BASELINE_Y
		if config.has("baseline_y"):
			baseline_y = int(config["baseline_y"])
		var remove_right_leaks := true
		if config.has("remove_right_leaks"):
			remove_right_leaks = bool(config["remove_right_leaks"])
		var offset_x := 0
		if config.has("offset_x"):
			offset_x = int(config["offset_x"])

		var frame_index := 0
		for rect: Rect2i in config["rects"]:
			var frame := _extract_frame(clean_sheet, rect, fixed_scale, frame_size, baseline_y, remove_right_leaks, offset_x)
			frame.save_png("%s/%s_%02d.png" % [OUT_DIR, animation_name, frame_index])
			frame_index += 1

	print("Generated player frames in %s" % OUT_DIR)
	quit()


func _load_clean_sheet(path: String) -> Image:
	var image := Image.load_from_file(path)
	if image == null:
		push_error("Could not load %s" % path)
		return Image.create(1, 1, false, Image.FORMAT_RGBA8)

	image.convert(Image.FORMAT_RGBA8)
	for y in image.get_height():
		for x in image.get_width():
			var color := image.get_pixel(x, y)
			if _is_sheet_background(color):
				color.a = 0.0
				image.set_pixel(x, y, color)

	return image


func _is_sheet_background(color: Color) -> bool:
	if color.a < 0.05:
		return true

	var max_channel: float = max(color.r, max(color.g, color.b))
	var min_channel: float = min(color.r, min(color.g, color.b))
	var saturation: float = 0.0 if max_channel <= 0.0 else (max_channel - min_channel) / max_channel
	var low_saturation: bool = saturation < 0.28
	var light: bool = max_channel > 0.55 and color.r > 0.48 and color.g > 0.48 and color.b > 0.48
	return light and low_saturation


func _extract_frame(sheet: Image, rect: Rect2i, fixed_scale: float = -1.0, frame_size: Vector2i = FRAME_SIZE, baseline_y: int = BASELINE_Y, remove_right_leaks: bool = true, offset_x: int = 0) -> Image:
	var crop := sheet.get_region(rect)
	_remove_background_fringe(crop)
	if remove_right_leaks:
		_remove_right_border_leaks(crop)
	var bounds := _content_bounds(crop)
	var trimmed := crop.get_region(bounds)
	var output := Image.create(frame_size.x, frame_size.y, false, Image.FORMAT_RGBA8)
	output.fill(Color(0, 0, 0, 0))

	var scale: float = fixed_scale
	if scale <= 0.0:
		scale = min(float(frame_size.x - 16) / float(trimmed.get_width()), float(frame_size.y - 16) / float(trimmed.get_height()))
	var scaled_size := Vector2i(maxi(1, int(trimmed.get_width() * scale)), maxi(1, int(trimmed.get_height() * scale)))
	trimmed.resize(scaled_size.x, scaled_size.y, Image.INTERPOLATE_NEAREST)

	var destination := Vector2i(
		int((frame_size.x - scaled_size.x) * 0.5) + offset_x,
		baseline_y - scaled_size.y
	)
	output.blit_rect(trimmed, Rect2i(Vector2i.ZERO, scaled_size), destination)
	_remove_background_fringe(output)
	_remove_far_right_islands(output)
	return output


func _remove_right_border_leaks(image: Image) -> void:
	var visited := {}
	var last_x := image.get_width() - 1

	for y in image.get_height():
		if image.get_pixel(last_x, y).a > 0.05:
			var start := Vector2i(last_x, y)
			if visited.has(start):
				continue

			var component := _collect_component(image, start, visited)
			if component.size() <= 900:
				for point: Vector2i in component:
					var color := image.get_pixel(point.x, point.y)
					color.a = 0.0
					image.set_pixel(point.x, point.y, color)


func _collect_component(image: Image, start: Vector2i, visited: Dictionary) -> Array[Vector2i]:
	var stack: Array[Vector2i] = [start]
	var component: Array[Vector2i] = []

	while not stack.is_empty():
		var point: Vector2i = stack.pop_back()
		if point.x < 0 or point.y < 0 or point.x >= image.get_width() or point.y >= image.get_height():
			continue

		if visited.has(point):
			continue

		visited[point] = true
		var color := image.get_pixel(point.x, point.y)
		if color.a <= 0.05:
			continue

		component.append(point)

		stack.append(Vector2i(point.x - 1, point.y))
		stack.append(Vector2i(point.x + 1, point.y))
		stack.append(Vector2i(point.x, point.y - 1))
		stack.append(Vector2i(point.x, point.y + 1))

	return component


func _remove_far_right_islands(image: Image) -> void:
	var visited := {}

	for y in image.get_height():
		for x in image.get_width():
			var point := Vector2i(x, y)
			if visited.has(point):
				continue

			if image.get_pixel(x, y).a <= 0.05:
				continue

			var component := _collect_component(image, point, visited)
			if component.is_empty():
				continue

			var min_x := image.get_width()
			var max_x := 0
			var min_y := image.get_height()
			var max_y := 0

			for pixel: Vector2i in component:
				min_x = mini(min_x, pixel.x)
				max_x = maxi(max_x, pixel.x)
				min_y = mini(min_y, pixel.y)
				max_y = maxi(max_y, pixel.y)

			var width := max_x - min_x + 1
			var height := max_y - min_y + 1
			var area := component.size()
			var far_right := min_x > int(image.get_width() * 0.86)
			var tiny_scrap := width < 28 and height < 40 and area < 450

			if far_right and tiny_scrap:
				for pixel: Vector2i in component:
					var color := image.get_pixel(pixel.x, pixel.y)
					color.a = 0.0
					image.set_pixel(pixel.x, pixel.y, color)


func _remove_background_fringe(image: Image) -> void:
	var source := image.duplicate()

	for y in image.get_height():
		for x in image.get_width():
			var color: Color = source.get_pixel(x, y)
			if color.a <= 0.05:
				continue

			if _is_white_halo(color) and _touches_transparent_or_background(source, x, y):
				color.a = 0.0
				image.set_pixel(x, y, color)


func _is_white_halo(color: Color) -> bool:
	var max_channel: float = max(color.r, max(color.g, color.b))
	var min_channel: float = min(color.r, min(color.g, color.b))
	var saturation: float = 0.0 if max_channel <= 0.0 else (max_channel - min_channel) / max_channel
	var very_light: bool = max_channel > 0.64 and min_channel > 0.46
	var pale: bool = max_channel > 0.50 and saturation < 0.20
	return very_light or pale


func _touches_transparent_or_background(image: Image, x: int, y: int) -> bool:
	for offset_y in range(-1, 2):
		for offset_x in range(-1, 2):
			if offset_x == 0 and offset_y == 0:
				continue

			var sample_x: int = x + offset_x
			var sample_y: int = y + offset_y
			if sample_x < 0 or sample_y < 0 or sample_x >= image.get_width() or sample_y >= image.get_height():
				return true

			var neighbor: Color = image.get_pixel(sample_x, sample_y)
			if neighbor.a <= 0.05 or _is_sheet_background(neighbor):
				return true

	return false


func _content_bounds(image: Image) -> Rect2i:
	var min_x := image.get_width()
	var min_y := image.get_height()
	var max_x := 0
	var max_y := 0

	for y in image.get_height():
		for x in image.get_width():
			if image.get_pixel(x, y).a > 0.05:
				min_x = mini(min_x, x)
				min_y = mini(min_y, y)
				max_x = maxi(max_x, x)
				max_y = maxi(max_y, y)

	if min_x > max_x or min_y > max_y:
		return Rect2i(0, 0, image.get_width(), image.get_height())

	var padding := 3
	min_x = maxi(0, min_x - padding)
	min_y = maxi(0, min_y - padding)
	max_x = mini(image.get_width() - 1, max_x + padding)
	max_y = mini(image.get_height() - 1, max_y + padding)
	return Rect2i(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
