extends Area2D

@export var speed: float = 680.0
@export var damage: int = 12
@export var lifetime: float = 1.8

var direction := Vector2.RIGHT


func _ready() -> void:
	body_entered.connect(_on_body_entered)
	area_entered.connect(_on_area_entered)
	await get_tree().create_timer(lifetime).timeout
	queue_free()


func _physics_process(delta: float) -> void:
	global_position += direction * speed * delta


func setup(start_position: Vector2, shot_direction: Vector2) -> void:
	global_position = start_position
	direction = shot_direction.normalized()
	rotation = direction.angle()


func _on_body_entered(body: Node2D) -> void:
	_hit(body)


func _on_area_entered(area: Area2D) -> void:
	_hit(area)


func _hit(target: Node) -> void:
	var damage_target := target
	if not damage_target.has_method("take_damage") and target.get_parent() != null:
		damage_target = target.get_parent()

	if damage_target.is_in_group("player") and damage_target.has_method("can_be_hit_by_bullet") and not damage_target.can_be_hit_by_bullet(global_position):
		return

	if damage_target.has_method("apply_projectile_hit") and damage_target.is_in_group("player"):
		damage_target.apply_projectile_hit(damage, global_position)
		queue_free()
		return

	if damage_target.has_method("take_damage") and damage_target.is_in_group("player"):
		damage_target.take_damage(damage)
		queue_free()
