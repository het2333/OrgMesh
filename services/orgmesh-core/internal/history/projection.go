package history

func Project(req ProjectionRequest) (ProjectionResponse, error) {
	if err := req.Validate(); err != nil {
		return ProjectionResponse{}, err
	}
	rows := make([]Row, 0, len(req.Facts))
	for _, f := range req.Facts {
		rows = append(rows, Row{
			PlatformTaskID: f.PlatformID, TaskID: f.EngineTaskID, PresentationID: f.DeckID,
			Status: f.State, ProjectID: f.VisibleProjectID, SourceChatID: f.VisibleSourceChatID,
			CreatedAt: f.CreatedAt, UpdatedAt: f.UpdatedAt,
		})
	}
	return ProjectionResponse{Version: 1, RequestID: req.RequestID, Rows: rows}, nil
}
