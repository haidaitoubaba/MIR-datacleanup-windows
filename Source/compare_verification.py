"""Compare scientific outputs from source and frozen verification sessions."""
import argparse
import json
from pathlib import Path
import numpy as np


def compare(left, right):
    a = json.loads((left / 'session.json').read_text(encoding='utf-8'))
    b = json.loads((right / 'session.json').read_text(encoding='utf-8'))
    assert a['properties'].keys() == b['properties'].keys()
    maximum_error = 0.0
    for name, pa in a['properties'].items():
        pb = b['properties'][name]
        assert pa['halves'] == pb['halves'], name
        assert pa['decisions'] == pb['decisions'], name
        assert pa['config'] == pb['config'], name
        np.testing.assert_allclose(pa['pca']['variance'], pb['pca']['variance'], rtol=1e-8, atol=1e-10)
        for half in ['A', 'B']:
            ra = pa['diagnostics'][half]['rows']
            rb = pb['diagnostics'][half]['rows']
            assert len(ra) == len(rb), name
            for xa, xb in zip(ra, rb):
                for key in ['File Name', 'Preprocessing', 'Selection Rank', 'Diagnostic Rank']:
                    assert xa[key] == xb[key], (name, key)
                for key in ['Calibration Prediction', 'Transformed Prediction', 'Studentised Residual']:
                    np.testing.assert_allclose(xa[key], xb[key], rtol=1e-8, atol=1e-10)
                    maximum_error = max(maximum_error, abs(xa[key] - xb[key]))
    return {'passed': True, 'properties': len(a['properties']),
            'max_absolute_prediction_or_residual_difference': maximum_error,
            'rtol': 1e-8, 'atol': 1e-10,
            'baseline': str(left), 'comparison': str(right)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = compare(args.left, args.right)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
