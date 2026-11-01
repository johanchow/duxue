// Package interfaces translates command-line arguments, without constructing IO adapters.
package interfaces

import (
	"errors"
	"flag"
	"io"
)

type Options struct{ Command, ConfigPath string }

func Parse(args []string) (Options, error) {
	var options Options
	if len(args) == 0 {
		return options, errors.New("usage: duxue-gateway <config-check|run|status> -config <file>")
	}
	command := args[0]
	if command != "run" && command != "config-check" && command != "status" {
		return options, errors.New("unknown command")
	}
	flags := flag.NewFlagSet(command, flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	path := flags.String("config", "config.yaml", "configuration file")
	if err := flags.Parse(args[1:]); err != nil || flags.NArg() != 0 {
		return options, errors.New("invalid command arguments")
	}
	return Options{Command: command, ConfigPath: *path}, nil
}
