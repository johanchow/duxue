// Package bootstrap is the only composition root for concrete IO adapters.
package bootstrap

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
	"github.com/johanchow/duxue/duxue-gateway/internal/infrastructure"
	"github.com/johanchow/duxue/duxue-gateway/internal/interfaces"
)

func Execute(ctx context.Context, args []string, out, stderr io.Writer) int {
	slog.SetDefault(slog.New(slog.NewJSONHandler(stderr, nil)))
	if err := execute(ctx, args, out); err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	return 0
}
func execute(ctx context.Context, args []string, out io.Writer) error {
	options, err := interfaces.Parse(args)
	if err != nil {
		return err
	}
	config, err := infrastructure.LoadConfig(options.ConfigPath, options.Command != "status")
	if err != nil {
		return err
	}
	if options.Command == "config-check" {
		_, err = io.WriteString(out, "configuration valid\n")
		return err
	}
	store, err := infrastructure.OpenStore(config, options.Command == "status")
	if err != nil {
		return errors.New("cannot open state directory; check permissions, initialization and instance lock")
	}
	defer store.Close()
	if options.Command == "status" {
		health, err := application.GetGatewayStatus(store)
		if err != nil {
			return errors.New("cannot query gateway state")
		}
		return json.NewEncoder(out).Encode(health)
	}
	cloud := infrastructure.NewCloud(config.APIBaseURL, os.Getenv(config.TokenEnv))
	defer cloud.Close()
	runner := application.Runner{Config: config, Repository: store, Cloud: cloud, Sources: infrastructure.SourceFactory(config.FFmpeg)}
	return runner.Run(ctx)
}
