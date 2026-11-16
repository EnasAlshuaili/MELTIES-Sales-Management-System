const cart = {};
const fmt = n => 'OMR ' + Number(n).toFixed(3);
const cartItems = document.getElementById('cart-items');
const totalEl = document.getElementById('cart-total');
const countEl = document.getElementById('cart-count');
function renderCart(){
  const entries = Object.values(cart);
  cartItems.innerHTML = '';
  if(!entries.length){cartItems.innerHTML='<p class="empty-cart">Your sweet picks will appear here.</p>';}
  let total=0, count=0;
  entries.forEach(item=>{
    total += item.price*item.quantity; count += item.quantity;
    const row=document.createElement('div'); row.className='cart-row';
    row.innerHTML=`<div><b>${escapeHtml(item.name)}</b><small>${fmt(item.price)}</small><div class="qty-controls"><button type="button" data-action="minus" data-id="${item.id}">−</button><span>${item.quantity}</span><button type="button" data-action="plus" data-id="${item.id}">+</button><button type="button" class="remove-item" data-action="remove" data-id="${item.id}">Remove</button></div></div><strong>${fmt(item.price*item.quantity)}</strong>`;
    cartItems.appendChild(row);
  });
  totalEl.textContent=fmt(total); countEl.textContent=`${count} item${count===1?'':'s'}`;
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
document.querySelectorAll('.add-btn').forEach(btn=>btn.addEventListener('click',()=>{
  const id=btn.dataset.id, stock=Number(btn.dataset.stock);
  if((cart[id]?.quantity||0)>=stock){alert('You have reached the available stock for this product.');return;}
  if(!cart[id])cart[id]={id, name:btn.dataset.name, price:Number(btn.dataset.price), quantity:0, stock};
  cart[id].quantity++; renderCart(); btn.textContent='Added ✓'; setTimeout(()=>btn.textContent='Add to cart +',900);
}));
cartItems.addEventListener('click',e=>{
  const b=e.target.closest('button[data-action]'); if(!b)return;
  const item=cart[b.dataset.id]; if(!item)return;
  if(b.dataset.action==='plus' && item.quantity<item.stock)item.quantity++;
  if(b.dataset.action==='minus')item.quantity--;
  if(b.dataset.action==='remove')item.quantity=0;
  if(item.quantity<=0)delete cart[b.dataset.id];
  renderCart();
});
document.getElementById('order-type').addEventListener('change',e=>{
  document.getElementById('address-label').classList.toggle('hidden',e.target.value!=='Delivery');
});
document.getElementById('checkout-form').addEventListener('submit',async e=>{
  e.preventDefault();
  const msg=document.getElementById('checkout-message');
  const items=Object.values(cart).map(x=>({product_id:Number(x.id),quantity:x.quantity}));
  if(!items.length){msg.className='error-message';msg.textContent='Add at least one cookie to your basket.';return;}
  const data=Object.fromEntries(new FormData(e.target).entries()); data.items=items;
  const button=e.target.querySelector('button[type=submit]'); button.disabled=true; button.textContent='Placing order…';
  try{
    const response=await fetch('/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result=await response.json();
    if(!response.ok)throw new Error(result.message||'Could not place order.');
    msg.className='success-message';msg.innerHTML=`Thank you! Your order <b>#${result.order_id}</b> is confirmed. Total: <b>${result.total}</b>. We'll contact you soon.`;
    Object.keys(cart).forEach(k=>delete cart[k]);renderCart();e.target.reset();document.getElementById('address-label').classList.add('hidden');
    document.querySelectorAll('.add-btn').forEach(b=>b.dataset.stock=Math.max(0,Number(b.dataset.stock)-(items.find(i=>i.product_id===Number(b.dataset.id))?.quantity||0)));
  }catch(err){msg.className='error-message';msg.textContent=err.message;}
  finally{button.disabled=false;button.textContent='Place my order';}
});
