const display = document.getElementById('display');
const buttons = document.querySelectorAll('.btn');
let current = '';

buttons.forEach(btn => {
    btn.addEventListener('click', () => {
        const val = btn.getAttribute('data-value');
        if (btn.id === 'clear') {
            current = '';
            display.value = '';
        } else if (btn.id === 'equal') {
            try {
                // gunakan eval dengan hati-hati
                const result = eval(current);
                display.value = result;
                current = result.toString();
            } catch (e) {
                display.value = 'Error';
                current = '';
            }
        } else {
            current += val;
            display.value = current;
        }
    });
});
