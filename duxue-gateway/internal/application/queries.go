package application

type HealthQuery interface {
	Health() ([]CameraHealth, error)
}

func GetGatewayStatus(query HealthQuery) ([]CameraHealth, error) { return query.Health() }
